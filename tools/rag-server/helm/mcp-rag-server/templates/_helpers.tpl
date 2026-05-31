{{- define "mcp-rag-server.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "mcp-rag-server.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "mcp-rag-server.labels" -}}
helm.sh/chart: {{ include "mcp-rag-server.name" . }}
app.kubernetes.io/name: {{ include "mcp-rag-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "mcp-rag-server.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-rag-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
