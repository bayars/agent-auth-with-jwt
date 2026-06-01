{{- define "mcp-fastmcp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "mcp-fastmcp.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "mcp-fastmcp.labels" -}}
helm.sh/chart: {{ include "mcp-fastmcp.name" . }}
app.kubernetes.io/name: {{ include "mcp-fastmcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "mcp-fastmcp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mcp-fastmcp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
