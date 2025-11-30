{{- define "llm-router.fullname" -}}
{{- printf "%s-%s" .Release.Name "llm-router" | trunc 63 | trimSuffix "-" -}}
{{- end -}}