import os
import sys
from typing import Optional, List

from google import genai
from google.genai import types

from logger import print_panel, print_status, log_step, logger

import modal

# Cache a single sandbox per run so the agent can keep state across tool calls.
_shared_sandbox: Optional[modal.Sandbox] = None
_shared_gpu: Optional[str] = None  # Track which GPU the sandbox was created with
_selected_gpu: Optional[str] = None  # User-selected GPU for this run


def _build_generation_config(
    *,
    tools: Optional[list] = None,
    system_instruction: Optional[str] = None,
    disable_autofc: bool = False,
) -> types.GenerateContentConfig:
    """
    Build a GenerateContentConfig that:

    - Enables Gemini "thinking mode" with visible thought summaries.
    - Sets thinking_level=HIGH (recommended for Gemini 3 Pro).
    - Optionally disables automatic function calling so we can control
      when tools run and show thoughts before actions.
    """
    thinking_config = types.ThinkingConfig(
        thinking_level=types.ThinkingLevel.HIGH,
        include_thoughts=True,
    )

    config_kwargs = {
        "tools": tools,
        "system_instruction": system_instruction,
        "thinking_config": thinking_config,
    }

    if disable_autofc:
        # Turn off automatic Python function calling so we get function_call
        # parts back and can execute tools manually in our loop.
        config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
            disable=True
        )

    return types.GenerateContentConfig(**config_kwargs)


def _get_shared_sandbox(gpu: Optional[str]) -> modal.Sandbox:
    """Create (once) and return a persistent sandbox for this run."""
    global _shared_sandbox, _shared_gpu
    if _shared_sandbox is not None:
        # Reuse only if GPU selection matches
        if gpu == _shared_gpu:
            return _shared_sandbox
        _close_shared_sandbox()

    log_step("EXECUTION", "Initializing shared Sandbox...")

    # Define a robust image with common dependencies (built once).
    image = (
        modal.Image.debian_slim()
        .pip_install("numpy", "pandas", "torch", "scikit-learn", "matplotlib")
    )

    # Create a Modal App to associate with the Sandbox
    log_step("EXECUTION", "Looking up Modal App 'agent-sandbox-app'...")
    app = modal.App.lookup("agent-sandbox-app", create_if_missing=True)
    log_step("EXECUTION", "Modal App found/created.")

    # Keep the sandbox alive by running an inert loop; subcommands run via sandbox.exec.
    gpu_msg = f"gpu={gpu}" if gpu else "cpu-only"
    log_step("EXECUTION", f"Creating persistent Sandbox (keep-alive loop, {gpu_msg})...")
    _shared_sandbox = modal.Sandbox.create(
        "bash",
        "-lc",
        "while true; do sleep 3600; done",
        app=app,
        image=image,
        timeout=7200,
        gpu=gpu,
    )
    _shared_gpu = gpu
    log_step("EXECUTION", "Persistent Sandbox ready.")
    return _shared_sandbox


def _close_shared_sandbox():
    """Terminate the shared sandbox if it exists."""
    global _shared_sandbox
    if _shared_sandbox is not None:
        try:
            _shared_sandbox.terminate()
            log_step("EXECUTION", "Persistent Sandbox terminated.")
        except Exception as e:
            log_step("WARNING", f"Failed to terminate sandbox cleanly: {e}")
        _shared_sandbox = None


def execute_in_sandbox(code: str):
    """
    Executes Python code inside a persistent Modal Sandbox using sandbox.exec.

    This function is exposed to Gemini as a tool. The agent will decide when to
    call it, and we run it manually in the loop so that we can show the
    model's thoughts before the code executes.
    """
    try:
        sandbox = _get_shared_sandbox(_selected_gpu)

        log_step("EXECUTION", "Launching python exec inside Sandbox...")
        print_panel(code, "Sandbox Code", "code")

        # Run the snippet via exec; stdout/stderr are streamed text.
        proc = sandbox.exec("python", "-u", "-")

        proc.stdin.write(code.encode("utf-8"))
        proc.stdin.write_eof()
        proc.stdin.drain()  # Flush buffered stdin

        stdout: List[str] = []
        stderr: List[str] = []

        log_step("EXECUTION", "Reading stdout/stderr streams...")
        for part in proc.stdout:
            stdout.append(part)
            print(part, end="")

        for part in proc.stderr:
            stderr.append(part)
            print(part, end="", file=sys.stderr)

        log_step("EXECUTION", "Waiting for process exit...")
        exit_code = proc.wait()
        log_step("EXECUTION", f"Process exited with code {exit_code}")

        stdout_str = "".join(stdout)
        stderr_str = "".join(stderr)

        return f"Exit Code: {exit_code}\nSTDOUT:\n{stdout_str}\nSTDERR:\n{stderr_str}"

    except Exception as e:
        log_step("ERROR", f"Sandbox Execution Failed: {str(e)}")
        return f"Sandbox Execution Failed: {str(e)}"


def _build_system_prompt(gpu_hint: str) -> str:
    """System-level instructions for the Gemini agent."""
    return f"""You are an autonomous research scientist.
Your job is to rigorously verify the user's hypothesis using experiments
run in a Python sandbox.

Tool:
- `execute_in_sandbox(code: str)`: Runs a Python script in a persistent Modal Sandbox.
  - Preinstalled: numpy, pandas, torch, scikit-learn, matplotlib.
  - Compute: Sandbox GPU request for this run: {gpu_hint}.
  - The code runs as a normal Python script; no need to import `modal`.

Working loop:
1. **Think before acting.** Plan your next step in natural language.
   We will show these thoughts in the CLI, so keep them understandable.
2. **Act with tools.** When you need computation, call `execute_in_sandbox`
   with a complete, self-contained script.
3. **Observe and update.** Interpret tool results and decide what to do next.
4. **Finish clearly.** When you have confidently verified or falsified
   the hypothesis, write a short natural-language conclusion and then a
   final line that contains only `[DONE]`.
"""


def run_experiment_loop(hypothesis: str):
    """Main agent loop using Gemini 3 Pro with thinking + manual tool calling."""
    gpu_hint = _selected_gpu or "CPU"

    print_panel(f"Hypothesis: {hypothesis}", "Starting Experiment", "bold green")
    log_step("START", f"Hypothesis: {hypothesis}")
    print_status(f"Sandbox GPU request: {gpu_hint}", "info")
    print_status("Gemini thinking: HIGH (thought summaries visible)", "info")

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    # Expose the sandbox executor as a tool.
    tools = [execute_in_sandbox]
    system_prompt = _build_system_prompt(gpu_hint)

    # Initial conversation: just the hypothesis as a user message.
    history: List[types.Content] = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"Hypothesis: {hypothesis}")],
        )
    ]

    max_steps = 10

    for step in range(1, max_steps + 1):
        print_status(f"Step {step}...", "dim")

        try:
            response = client.models.generate_content(
                model="gemini-3-pro-preview",
                contents=history,
                config=_build_generation_config(
                    tools=tools,
                    system_instruction=system_prompt,
                    disable_autofc=True,  # manual tool loop
                ),
            )
        except Exception as e:
            print_status(f"API Error: {e}", "error")
            logger.error(f"API Error: {e}")
            break

        if not response.candidates:
            print_status("Empty response from model.", "warning")
            break

        candidate = response.candidates[0]
        model_content = candidate.content

        if not model_content or not model_content.parts:
            print_status("Empty content from model.", "warning")
            break

        # IMPORTANT: append the full model message (including thought signatures
        # and function call parts) so the SDK can preserve reasoning state.
        history.append(model_content)

        thoughts: List[str] = []
        messages: List[str] = []
        function_calls = []

        for part in model_content.parts:
            # Thought summaries from thinking mode.
            if getattr(part, "thought", False) and part.text:
                thoughts.append(part.text)

            # Function/tool call parts.
            if part.function_call:
                function_calls.append(part.function_call)

            # Regular assistant text (exclude thought parts so we don't double-print).
            if part.text and not getattr(part, "thought", False):
                messages.append(part.text)

        # 1. Show reasoning before any action.
        if thoughts:
            joined_thoughts = "\n\n".join(thoughts)
            print_panel(joined_thoughts, "Agent Thinking", "thought")
            log_step("THOUGHT", joined_thoughts)

        # 2. Show natural-language messages (plans, explanations, etc.).
        if messages:
            joined_messages = "\n\n".join(messages)
            print_panel(joined_messages, "Agent Message", "info")
            log_step("MODEL", joined_messages)

        combined_text = "\n".join(thoughts + messages)
        if "[DONE]" in combined_text:
            print_status("Agent signaled completion.", "success")
            break

        # If the model didn't call any tools this turn, assume we're done.
        if not function_calls:
            print_status(
                "No tool calls in this step; assuming experiment is complete.", "info"
            )
            break

        # 3. Execute requested tools (currently just execute_in_sandbox).
        for fn_call in function_calls:
            fn_name = fn_call.name
            fn_args = dict(fn_call.args or {})

            print_panel(f"{fn_name}({fn_args})", "Tool Call", "code")
            log_step("TOOL_CALL", f"{fn_name}({fn_args})")

            if fn_name == "execute_in_sandbox":
                result = execute_in_sandbox(**fn_args)
            else:
                result = (
                    f"Unsupported tool '{fn_name}'. "
                    "Only 'execute_in_sandbox' is available."
                )

            # Truncate long outputs to keep console readable.
            if isinstance(result, str) and len(result) > 20000:
                result = (
                    result[:10000]
                    + "\n...[TRUNCATED]...\n"
                    + result[-10000:]
                )

            print_panel(result, "Tool Result", "result")
            log_step("TOOL_RESULT", "Executed")

            # Feed the tool response back as a TOOL message with a functionResponse part.
            history.append(
                types.Content(
                    role="tool",
                    parts=[
                        types.Part.from_function_response(
                            name=fn_name,
                            response={"result": result},
                        )
                    ],
                )
            )

    # Final report generation.
    try:
        print_status("Generating Final Report...", "bold green")
        history.append(
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=(
                            "Generate a concise, information-dense report that explains "
                            "how you tested the hypothesis, what you observed, and your "
                            "final conclusion."
                        )
                    )
                ],
            )
        )

        final_response = client.models.generate_content(
            model="gemini-3-pro-preview",
            contents=history,
            # Still use thinking so the model can reason about its own trace,
            # but tools are not needed here.
            config=_build_generation_config(
                tools=None,
                system_instruction=system_prompt,
                disable_autofc=True,
            ),
        )

        final_text = final_response.text or ""
        print_panel(final_text, "Final Report", "bold green")
    finally:
        _close_shared_sandbox()
