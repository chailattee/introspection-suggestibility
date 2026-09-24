import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic
import openai

MODELS = {
    "claude-sonnet-5": "anthropic",
    "gpt-5.2": "openai",
    "qwen/qwen3.6-27b": "openrouter",
}
EFFORT = "medium"
TEMPERATURE = 1.0
MAX_TOKENS = 16000
SAMPLES = 10
WORKERS = 8
OUT = "responses.jsonl"

claude = anthropic.Anthropic()
gpt = openai.OpenAI()
openrouter = openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])


def to_chat(prompt):
    """A template is a plain user string, or {"system": ..., "messages": [...]} for multi-turn setups."""
    if isinstance(prompt, str):
        return None, [{"role": "user", "content": prompt}]
    return prompt.get("system"), prompt["messages"]


def call(model, prompt):
    """Returns (response_text, reasoning)."""
    system, messages = to_chat(prompt)
    match MODELS[model]:
        case "anthropic":
            r = claude.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                output_config={"effort": EFFORT},
                messages=messages,
                **({"system": system} if system else {}),
            )
            if r.stop_reason == "refusal":
                return "[REFUSAL]", None
            return "".join(b.text for b in r.content if b.type == "text"), None
        case "openai":
            r = gpt.responses.create(
                model=model,
                input=messages,
                instructions=system,
                reasoning={"effort": EFFORT},
                temperature=TEMPERATURE,
            )
            return r.output_text, None
        case "openrouter":
            r = openrouter.chat.completions.create(
                model=model,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                messages=([{"role": "system", "content": system}] if system else []) + messages,
                extra_body={"reasoning": {"enabled": True}},
            )
            msg = r.choices[0].message
            return msg.content, getattr(msg, "reasoning", None)


def retry(fn, *args, tries=5):
    for i in range(tries):
        try:
            return fn(*args)
        except Exception as e:
            status = getattr(e, "status_code", None)
            if i == tries - 1 or (status and 400 <= status < 500 and status != 429):
                raise
            print(f"retry {fn.__name__} ({e})", file=sys.stderr)
            time.sleep(2**i)


def main():
    if "--test" in sys.argv:
        for model in MODELS:
            text, reasoning = retry(call, model, "In one sentence, what is introspection?")
            print(f"--- {model}\n{text}\nreasoning: {(reasoning or '')[:200]!r}\n")
        return

    templates = json.load(open("templates.json"))
    only = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--model=")), None)
    n = int(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--samples=")), SAMPLES))

    done = set()
    if os.path.exists(OUT):
        for line in open(OUT):
            r = json.loads(line)
            done.add((r["model"], r["level"], r["paraphrase_id"], r["sample_idx"]))

    jobs = [
        (model, level, pid, s, prompt)
        for model in MODELS if not only or model == only
        for level, prompts in templates.items()
        for pid, prompt in enumerate(prompts)
        for s in range(n)
        if (model, level, pid, s) not in done
    ]
    print(f"{len(jobs)} calls to make ({len(done)} already done)")

    lock = threading.Lock()

    def run(job):
        model, level, pid, s, prompt = job
        text, reasoning = retry(call, model, prompt)
        row = dict(model=model, level=level, paraphrase_id=pid, sample_idx=s,
                   prompt=prompt, response_text=text, reasoning=reasoning)
        with lock, open(OUT, "a") as f:
            f.write(json.dumps(row) + "\n")

    with ThreadPoolExecutor(WORKERS) as ex:
        for i, _ in enumerate(ex.map(run, jobs), 1):
            if i % 20 == 0:
                print(f"{i}/{len(jobs)}")


if __name__ == "__main__":
    main()
