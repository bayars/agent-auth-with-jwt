{{- define "mcp-http-caller.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "mcp-http-caller.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "mcp-http-caller.labels" -}}
helm.sh/chart: {{- include "mcp-http-caller.name" . | nindent 1 }}
app.kubernetes.io/name: {{- include "mcp-http-caller.name" . | nindent 1 }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "mcp-http-caller.selectorLabels" -}}
app.kubernetes.io/name: {{- include "mcp-http-caller.name" . | nindent 1 }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
