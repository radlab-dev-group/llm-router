from typing import List, Dict

from llm_router_api.core.lb.strategies.weighted import DynamicWeightedStrategy


class AdaptiveStrategy(DynamicWeightedStrategy):
    """
    Adaptacyjna strategia równoważenia obciążenia.
    - Dziedziczy po DynamicWeightedStrategy (dynamiczne wagi + historia interwałów).
    - Uczy się online, aby minimalizować interwały między kolejnymi wyborami providera,
      z silną karą za "fail" (interwał < 0.5s) i za pogorszenie (bad_turn).
    - Mapuje przewidywany koszt na wagi wyboru (softmax z temperaturą i p_min).
    """

    def __init__(
        self,
        models_config_path: str,
        initial_providers: List[Dict] | None = None,
        history_size: int = 10_000,
        learning_rate: float = 0.1,
        temperature: float = 1.0,
        min_prob: float = 0.01,
        lambda_fail: float = 8.0,
        lambda_bad: float = 2.0,
        delta_bad: float = 0.05,
        ema_alpha_interval: float = 0.2,
        ema_alpha_fail: float = 0.3,
        ema_alpha_trend: float = 0.2,
        enable_decision_logging: bool = False,
    ) -> None:
        super().__init__(
            initial_providers=initial_providers,
            history_size=history_size,
            models_config_path=models_config_path,
        )
        # Parametry uczenia i mapowania
        self._lr = learning_rate
        self._tau = temperature
        self._p_min = min_prob
        self._lambda_fail = lambda_fail
        self._lambda_bad = lambda_bad
        self._delta_bad = delta_bad
        self._ema_alpha_interval = ema_alpha_interval
        self._ema_alpha_fail = ema_alpha_fail
        self._ema_alpha_trend = ema_alpha_trend
        self._enable_decision_logging = enable_decision_logging

        # Stan per provider: cechy i parametry modelu liniowego
        # θ: wektor wag dla cech [
        #   bias, ema_interval, ema_trend, recent_fail_rate, cooldown, load_proxy
        # ]
        self._theta: Dict[str, List[float]] = {}
        self._bias_init = 0.0

        # EMA metryk
        self._ema_interval: Dict[str, float] = {}
        self._ema_trend: Dict[str, float] = {}
        self._recent_fail_rate: Dict[str, float] = {}
        self._last_interval: Dict[str, float] = (
            {}
        )  # ostatni zaobserwowany interwał (do bad_turn)

        # Logity (z_ema) do wygładzania i wyliczania wag
        self._logits_ema: Dict[str, float] = {}

        # Persistencja (prosta, do ewentualnego zewn. użycia)
        self._last_persist_ts: float = 0.0
        self._persist_interval_sec: float = 4.0  # domyślnie 3–5 s; tu ustawiono 4 s

    def _ensure_provider_state(self, key: str) -> None:
        if key not in self._theta:
            # 6 cech:
            #   bias, ema_interval, ema_trend,
            #   recent_fail_rate, cooldown, load_proxy
            self._theta[key] = [0.0, 0.0, 0.0, 0.0, 0.2, -0.2]
        self._ema_interval.setdefault(key, 0.0)
        self._ema_trend.setdefault(key, 0.0)
        self._recent_fail_rate.setdefault(key, 0.0)
        self._last_interval.setdefault(key, None)  # type: ignore
        self._logits_ema.setdefault(key, 0.0)

    def _ema_update(self, prev: float, value: float, alpha: float) -> float:
        return (1 - alpha) * prev + alpha * value

    def _features(self, key: str, now: float) -> List[float]:
        self._ensure_provider_state(key)
        ema_interval = self._ema_interval[key]
        ema_trend = self._ema_trend[key]
        fail_rate = self._recent_fail_rate[key]
        last_ts = self._last_chosen_time.get(key)
        cooldown = 0.0
        if last_ts is not None:
            cooldown = max(0.0, min(1.0, (now - last_ts) / 3.0))  # T_cool ~ 3s
        load_proxy = 0.0
        if ema_interval > 1e-6:
            load_proxy = 1.0 / ema_interval
        # bias, ema_interval, ema_trend, recent_fail_rate, cooldown, load_proxy
        return [1.0, ema_interval, ema_trend, fail_rate, cooldown, load_proxy]

    def _predict_cost(self, theta: List[float], x: List[float]) -> float:
        # prosta warstwa liniowa
        return sum(t * xi for t, xi in zip(theta, x)) + self._bias_init

    def _softmax_weights(self, logits: List[float]) -> List[float]:
        # temperatura + stabilny softmax
        if not logits:
            return []
        m = max(logits)
        exps = [pow(2.718281828, (z - m) / max(1e-6, self._tau)) for z in logits]
        s = sum(exps)
        probs = [e / s for e in exps]
        # enforce p_min
        n = len(probs)
        p_min = min(self._p_min, 1.0 / max(1, n))
        if p_min > 0:
            # podnieś do p_min, a nadwyżkę zbierz z największych p
            adjusted = []
            deficit = 0.0
            for p in probs:
                if p < p_min:
                    deficit += p_min - p
                    adjusted.append(p_min)
                else:
                    adjusted.append(p)
            if deficit > 0:
                excess = sum(max(0.0, p - p_min) for p in adjusted)
                if excess > 1e-12:
                    scale = (excess - deficit) / excess
                    adjusted = [
                        (
                            (p_min + (p - p_min) * max(0.0, scale))
                            if p > p_min
                            else p_min
                        )
                        for p in adjusted
                    ]
                # renormalizacja
            total = sum(adjusted)
            if total > 0:
                probs = [p / total for p in adjusted]
        return probs

    def get_provider(self, model_name: str, providers: List[Dict]) -> Dict:
        """
        - Oblicza cechy i logity dla aktualnych providerów.
        - Mapuje na prawdopodobieństwa (softmax z temperaturą i p_min).
        - Deleguje wybór do WeightedStrategy (deterministyczna pseudo-losowość),
          ale zaktualizowanymi wagami dynamicznymi
          na podstawie przewidywanego kosztu.
        - Po wyborze rejestruje interwał w DynamicWeightedStrategy;
          faktyczna aktualizacja uczenia następuje przy kolejnym wywołaniu
          choose (gdy znany jest interwał).
        """
        if not providers:
            raise ValueError(f"No providers configured for model '{model_name}'")

        now = __import__("time").time()

        # 1) Wyznacz logity z modelu liniowego (ujemny koszt => wyższy logit)
        keys = [self._provider_key(cfg) for cfg in providers]
        logits = []
        for key in keys:
            self._ensure_provider_state(key)
            x = self._features(key, now)
            # przewidywany koszt -> logit = -cost
            z = -self._predict_cost(self._theta[key], x)
            # wygładź logit dla stabilności
            z_ema = self._ema_update(self._logits_ema[key], z, 0.2)
            self._logits_ema[key] = z_ema
            logits.append(z_ema)

        # 2) Softmax -> prawdopodobieństwa -> aktualizacja wag dynamicznych
        probs = self._softmax_weights(logits)
        for cfg, p in zip(providers, probs):
            key = self._provider_key(cfg)
            self.set_weight_by_key(key, p)

        # 3) Wybór providera wykorzystujący zaktualizowane wagi
        chosen_cfg = super().get_provider(model_name, providers)

        # 4) Rejestracja interwału (DynamicWeightedStrategy zapisze historię)
        #    oraz aktualizacja EMA metryk + nauka na podstawie poprzedniego interwału
        key = self._provider_key(chosen_cfg)
        now2 = __import__("time").time()
        self._on_after_choice(key, now2)

        # Persistencja okresowa (opcjonalna: tu tylko znacznik czasu i hook)
        if (now2 - self._last_persist_ts) >= self._persist_interval_sec:
            self._persist_snapshot()
            self._last_persist_ts = now2

        return chosen_cfg

    def _on_after_choice(self, key: str, now: float) -> None:
        """
        Po wyborze providera:
        - wyznacza nowy interwał z last_chosen_time,
        - aktualizuje EMA metryk,
        - jeśli istniał poprzedni interwał -> uczy model (regresja kosztu).
        """
        self._ensure_provider_state(key)

        prev_ts = self._last_chosen_time.get(key)
        interval = None
        if prev_ts is not None:
            interval = max(0.0, now - prev_ts)

        # Aktualizacje w DynamicWeightedStrategy (historia) już zachodzą w choose;
        # tutaj robimy metryki EMA i naukę.
        if interval is not None:
            # fail heurystyka
            fail_flag = 1.0 if interval < 0.5 else 0.0

            # poprzedni interwał do bad_turn
            prev_interval = self._last_interval.get(key)
            bad_turn = 0.0
            if prev_interval is not None and (
                interval > (prev_interval + self._delta_bad)
            ):
                bad_turn = 1.0

            # EMA interval i trend
            old_ema = self._ema_interval[key]
            new_ema = self._ema_update(old_ema, interval, self._ema_alpha_interval)
            self._ema_interval[key] = new_ema
            trend = interval - (
                prev_interval if prev_interval is not None else interval
            )
            self._ema_trend[key] = self._ema_update(
                self._ema_trend[key], trend, self._ema_alpha_trend
            )

            # EMA fail rate
            self._recent_fail_rate[key] = self._ema_update(
                self._recent_fail_rate[key], fail_flag, self._ema_alpha_fail
            )

            # zapis ostatniego interwału
            self._last_interval[key] = interval

            # uczenie: target kosztu = interwał + kary
            target_cost = (
                interval
                + self._lambda_fail * fail_flag
                + self._lambda_bad * bad_turn
            )

            # regresja liniowa online: minimalizujemy (pred - target)^2
            x = self._features(key, now)
            pred = self._predict_cost(self._theta[key], x)
            error = pred - target_cost
            # SGD update: θ := θ - lr * 2 * error * x
            grad_scale = 2.0 * error * self._lr
            theta = self._theta[key]
            for i in range(len(theta)):
                theta[i] -= grad_scale * x[i]
            self._theta[key] = theta

            # opcjonalne logowanie
            if self._enable_decision_logging:
                try:
                    # Minimalny, bezpieczny log na stdout; w praktyce można dodać logger
                    print(
                        f"[AB] key={key} interval={interval:.3f} fail={fail_flag:.0f} "
                        f"bad_turn={bad_turn:.0f} target={target_cost:.3f} "
                        f"pred={pred:.3f} err={error:.3f}"
                    )
                except Exception:
                    pass

    def _persist_snapshot(self) -> None:
        """
        Hook: w realnej implementacji zapisz snapshot parametrów do pliku.
        Przechowywane: theta, ema metryki, logits_ema, konfiguracja hiperparametrów.
        Tu pozostawione jako placeholder, aby nie ingerować w I/O bez wyraźnej prośby.
        """
        # Placeholder: można zaimplementować zapis do JSON/YAML w osobnym zadaniu.
        return

    def export_state(self) -> Dict:
        """Eksport stanu do serializacji."""
        return {
            "theta": self._theta,
            "ema_interval": self._ema_interval,
            "ema_trend": self._ema_trend,
            "recent_fail_rate": self._recent_fail_rate,
            "last_interval": self._last_interval,
            "logits_ema": self._logits_ema,
            "lr": self._lr,
            "tau": self._tau,
            "p_min": self._p_min,
            "lambda_fail": self._lambda_fail,
            "lambda_bad": self._lambda_bad,
            "delta_bad": self._delta_bad,
            "ema_alpha_interval": self._ema_alpha_interval,
            "ema_alpha_fail": self._ema_alpha_fail,
            "ema_alpha_trend": self._ema_alpha_trend,
        }

    def import_state(self, state: Dict) -> None:
        """Import stanu z serializacji."""
        self._theta = dict(state.get("theta", {}))
        self._ema_interval = dict(state.get("ema_interval", {}))
        self._ema_trend = dict(state.get("ema_trend", {}))
        self._recent_fail_rate = dict(state.get("recent_fail_rate", {}))
        self._last_interval = dict(state.get("last_interval", {}))
        self._logits_ema = dict(state.get("logits_ema", {}))
        self._lr = float(state.get("lr", self._lr))
        self._tau = float(state.get("tau", self._tau))
        self._p_min = float(state.get("p_min", self._p_min))
        self._lambda_fail = float(state.get("lambda_fail", self._lambda_fail))
        self._lambda_bad = float(state.get("lambda_bad", self._lambda_bad))
        self._delta_bad = float(state.get("delta_bad", self._delta_bad))
        self._ema_alpha_interval = float(
            state.get("ema_alpha_interval", self._ema_alpha_interval)
        )
        self._ema_alpha_fail = float(
            state.get("ema_alpha_fail", self._ema_alpha_fail)
        )
        self._ema_alpha_trend = float(
            state.get("ema_alpha_trend", self._ema_alpha_trend)
        )
