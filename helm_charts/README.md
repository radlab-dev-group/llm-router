# LLM‑Router Helm Chart
Quick summary – This Helm chart deploys the LLM‑Router application with its optional Redis dependency. It works on any Kubernetes 1.19+ cluster and can be customized via values.yaml, environment variables, or the --set flag.
## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Chart layout](#chart-layout)
3. [Dependencies](#dependencies)
4. [Installing the chart](#installing-the-chart)
5. [Customising the deployment](#customising-the-deployment)

## Prerequisites

| Requirement | Why we need it |
| --- | --- |
| **Kubernetes** (v1.19 or newer) | The chart creates Deployments, Services, Ingresses, ConfigMaps, … |
| **Helm** (v3.x) | Used to render and apply the chart |
| **Access to a container registry** (e.g., Docker Hub, Quay, your private registry) | The chart pulls the image defined in `llm-router``values.yaml` |
| (Optional) **cert‑manager** | If you enable TLS for the Ingress, cert‑manager will provision certificates |
## Chart layout
``` 
helm_charts/
└─ llm-router/
   ├─ Chart.yaml          # Chart metadata
   ├─ values.yaml         # Default values
   ├─ values-dev.yaml     # Development‑specific overrides
   ├─ templates/
   │   ├─ _helpers.tpl    # Helper functions (name, labels, etc.)
   │   ├─ deployment.yaml # Deployment definition
   │   ├─ service.yaml    # Service definition
   │   ├─ ingress.yaml    # Ingress definition (optional)
   │   ├─ configmap.yaml  # ConfigMap for runtime env vars
   │   └─ configmap-models.yaml # ConfigMap for `models-config.json`
   └─ charts/
       └─ redis-23.2.12.tgz   # Bitnami Redis sub‑chart (dependency)
```

 
## Dependencies
The chart depends on Redis. The dependency is declared in Chart.yaml and pulled automatically when you run helm dependency update.
``` yaml
# Chart.yaml
dependencies:
  - name: redis
    version: "23.2.12"
    repository: "oci://registry-1.docker.io/bitnamicharts"
    condition: redis.enabled
```

Adding / updating dependencies
``` bash
# From the chart root (helm_charts/llm-router)
helm dependency update .
```

You can disable the Redis sub‑chart with:
``` bash
--set redis.enabled=false
```

 
## Installing the chart
``` bash
helm upgrade --install my-llm-router ./helm_charts/llm-router \
  --namespace my-namespace \
  --create-namespace
```

## Customising the deployment  

You can tailor the **LLM‑Router** Helm chart to your environment in three different ways. Pick the approach that best fits the task at hand.

| Method | When to use |
|--------|--------------|
| **Edit `values.yaml` and run `helm upgrade`** | Long‑term, version‑controlled configuration that lives in source control. |
| **Pass `--set` flags on the command line** | One‑off tweaks, CI pipelines, quick experiments, or when you need to override just a handful of values. |
| **Provide a custom values file (`-f my-values.yaml`)** | Complex overrides, reusable profiles, or when you prefer to keep the changes in a separate, shareable file. |

Below are concrete examples for the two most common scenarios: using a custom values file **and** using `--set` flags.

---

### 1️⃣ Using a custom values file  

Create a file (e.g. `my-values.yaml`) with the settings you want to override:

```yaml
# my-values.yaml
ingress:
  enabled: true
  className: traefik
  hosts:
    - host: my-custom.cluster.local
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - my-custom.cluster.local
      secretName: llm-router-tls

image:
  tag: latest          # pull the latest container image

web_host: my-custom.cluster.local   # the hostname used by the app & Ingress
```


Deploy (or upgrade) the chart with this file:

```shell script
helm upgrade --install llm-router ./helm_charts/llm-router \
  -f my-values.yaml
```

---

### 2️⃣ Using `--set` flags  

If you only need to change a few values, the `--set` syntax is handy:

```shell script
helm upgrade --install llm-router ./helm_charts/llm-router \
  --set ingress.enabled=true \
  --set web_host=llm2.k3s.radlab.dev \
  --set image.tag=latest
```


| Flag                   | Effect |
|------------------------|--------|
| `ingress.enabled=true` | Turns on the Ingress resource (otherwise it’s omitted). |
| `llm-1.cluster.local`  | Sets the host name used both in the Ingress rule and the application’s configuration (`LLM_ROUTER_WEB_HOST`). |
| `image.tag=latest`     | Pulls the `latest` image tag instead of the default chart‑version tag. |
