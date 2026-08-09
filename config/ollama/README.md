# Ollama configuration

`Modelfile` defines **cobalt**, the model the app actually calls. It layers a
context window, sampling parameters and a system prompt over the base weights —
it does not copy them, so it adds no meaningful disk.

```sh
ollama create cobalt -f config/ollama/Modelfile   # ./cobalt-start.sh --llm does this
ollama show cobalt --modelfile                    # what is actually loaded
ollama ps                                         # PROCESSOR must say 100% GPU
```

## Always send `"think": false`

qwen3.5 is a reasoning model. Left to itself it spends thousands of tokens
thinking before answering, which for summarisation buys nothing:

| | wall | tokens | reasoning |
| --- | --- | --- | --- |
| `think: true` | 52.7s | 3220 | 13500 chars |
| `think: false` | **2.4s** | 124 | none |

The shorter run also produced the better summary. `PARAMETER think` is rejected
by `ollama create`, so this has to go in the request body — it is the one
setting that could not be moved into this file.

## Why a Modelfile rather than per-request options

Parameters set here are version-controlled and apply to every call. Passing
`num_ctx` per request works too, but then the single most damaging setting —
the context window — lives in application code where a missed call site
silently truncates the input.

## Changing the base model

Edit the `FROM` line, then re-run `./cobalt-start.sh --llm`. The name `cobalt` stays
the same, so nothing in the app needs to change.

## Running it in a container instead

The default here assumes Ollama runs on the host, which is the sane choice when
the host has an NVIDIA GPU: no container toolkit needed, and the weights are
already downloaded. `./cobalt-start.sh --llm --container-ollama` runs it in Docker
instead — that path needs the NVIDIA Container Toolkit, or it silently falls
back to CPU.
