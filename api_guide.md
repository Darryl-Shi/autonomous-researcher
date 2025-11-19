# AI Researcher HTTP API

This document describes the lightweight HTTP API that wraps the existing CLI entrypoint (`main.py`).

The API **does not** change any of the research logic – it simply spawns the current CLI in a subprocess and streams back everything it prints, so you can build a rich front-end on top.

---

## Getting started

1. Install dependencies:

```bash
pip install -r requirements.txt