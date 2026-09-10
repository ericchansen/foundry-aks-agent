---
title: Overview
description: One agent on AKS, one model call, and a trace you can follow in Foundry.
---

# Run on AKS. Trace in Foundry.

One Pydantic AI agent, an authenticated HTTP endpoint, and one model call per
request. Foundry adds an external-agent record and attributed traces.
**Execution stays on AKS.**

<div class="diagram" role="region" aria-label="Request and telemetry architecture; scroll to see the full diagram on small screens" tabindex="0" markdown="1">

![The CLI reaches an authenticated service and Pydantic AI agent inside AKS through a loopback port-forward. The agent calls the Foundry model. Separately, agent telemetry is exported to project-linked Application Insights and viewed in Foundry.](assets/architecture.svg)

</div>

[Open diagram full-size](assets/architecture.svg){ .figure-link }
&nbsp; [Architecture and sources](architecture.md){ .figure-link }

<div class="paths" markdown="1">

<section markdown="1">

## Understand the design

Follow the [request and telemetry paths](architecture.md), then review the
[authentication and security boundaries](security.md). Path A is metadata and
observability integration, not another runtime.

</section>
<section markdown="1">

## Reproduce the demo

Set up [local development](development.md), provision the
[dedicated infrastructure](infrastructure.md), then
[deploy and demonstrate](deployment.md) an authenticated model request.

</section>
</div>

## What is demonstrated

The [September 9-10 deployment record](evidence.md) connects a real model answer
to its deployed image, pod, stable agent ID, and native request/agent/model
trace chain. The same trace was visible in the external agent's Foundry view.
This is a dated record, not a live availability indicator.

## Deliberately small

This is a single-operator, synthetic-data demo: no agent tools, conversation
store, retries, or public application ingress. Path B (APIM/AI Gateway),
evaluation, document search, ingestion, and an agent web UI remain deferred.
See the [runtime boundaries](security.md) and Microsoft's
[external-agent contract (preview)](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/register-external-agent).
