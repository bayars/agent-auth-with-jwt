{{- define "mcp-a2a-bridge.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- define "mcp-a2a-bridge.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- define "mcp-a2a-bridge.labels" -}}
helm.sh/chart: {{ include "mcp-a2a-bridge.name" . }}
app.kubernetes.io/name: {{ include "mcp-a2a-bridge.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
{{- define "mcp-a2a-bridge.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-a2a-bridge.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
