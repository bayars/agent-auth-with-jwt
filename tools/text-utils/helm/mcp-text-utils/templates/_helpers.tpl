{{- define "mcp-text-utils.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "mcp-text-utils.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "mcp-text-utils.labels" -}}
helm.sh/chart: {{- include "mcp-text-utils.name" . | nindent 1 }}
app.kubernetes.io/name: {{- include "mcp-text-utils.name" . | nindent 1 }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "mcp-text-utils.selectorLabels" -}}
app.kubernetes.io/name: {{- include "mcp-text-utils.name" . | nindent 1 }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
