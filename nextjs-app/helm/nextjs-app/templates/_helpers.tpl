{{- define "nextjs-app.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nextjs-app.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "nextjs-app.labels" -}}
helm.sh/chart: {{ include "nextjs-app.name" . }}
app.kubernetes.io/name: {{ include "nextjs-app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "nextjs-app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nextjs-app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
