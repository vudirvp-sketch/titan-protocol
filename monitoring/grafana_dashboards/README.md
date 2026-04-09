# TITAN Protocol Grafana Dashboards

This directory contains Grafana dashboard configurations for monitoring TITAN Protocol.

## Dashboards

### 1. Overview Dashboard (`titan-overview.json`)
High-level metrics and health status for TITAN components.

### 2. Performance Dashboard (`titan-performance.json`)
Detailed latency and throughput metrics.

### 3. Security Dashboard (`titan-security.json`)
Security alerts and injection detection metrics.

### 4. Resilience Dashboard (`titan-resilience.json`)
Circuit breaker states and degradation metrics.

---

## Import Instructions

1. Open Grafana UI
2. Navigate to Dashboards > Import
3. Upload the JSON file or paste the dashboard JSON
4. Select the Prometheus data source
5. Click Import

---

## Data Source Requirements

- Prometheus endpoint: `/metrics`
- Scrape interval: 15s (recommended)
- Metrics prefix: `titan_`

---

## Panels Overview

### Overview Dashboard

| Panel | Description |
|-------|-------------|
| Request Rate | Requests per second |
| Profile Distribution | Pie chart of detected profiles |
| Intent Distribution | Bar chart of intent types |
| Error Rate | Error percentage |
| Active Sessions | Current active sessions |

### Performance Dashboard

| Panel | Description |
|-------|-------------|
| Profile Detection Latency | P50, P95, P99 latency |
| Intent Enrichment Latency | P50, P95, P99 latency |
| End-to-End Latency | Full pipeline latency |
| Throughput | Requests per minute |

### Security Dashboard

| Panel | Description |
|-------|-------------|
| Injection Attempts | Prompt injection detection count |
| Blocked Requests | Rejected requests count |
| Security Alerts | Alert breakdown by severity |
| Session Violations | Session security violations |

### Resilience Dashboard

| Panel | Description |
|-------|-------------|
| Circuit Breaker States | Current state of all circuits |
| Degradation Level | Current degradation level |
| Fallback Triggers | Fallback activation count |
| Retry Statistics | Retry success/failure rates |
