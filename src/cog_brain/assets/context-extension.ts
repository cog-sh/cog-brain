// Read-only lifecycle context; code execution uses the host's existing executor.
import { spawn } from "node:child_process";

const python = __PYTHON__;
const harness = __HARNESS__;

export default function (pi: any) {
  let lastPacket = "";
  let lastPrompt = "";
  const load = (cwd: string, prompt = ""): Promise<string> => new Promise(resolve => {
    const child = spawn(python, ["-m", "cog_brain.cli", "hook", "--harness", harness],
      { cwd, stdio: ["pipe", "pipe", "pipe"] });
    let output = "";
    let settled = false;
    const finish = (text: string) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(text);
    };
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      finish("cog-brain context timed out; memory was not loaded.");
    }, 9000);
    child.stdout.on("data", data => {
      output += data.toString();
      if (output.length > 32000) {
        child.kill("SIGKILL");
        finish("cog-brain context exceeded output limit; memory was not loaded.");
      }
    });
    child.stderr.resume();
    child.on("error", () => finish("cog-brain could not start; memory was not loaded."));
    child.stdin.on("error", () => {});
    child.on("close", code => finish(code === 0 ? output.trim() :
      "cog-brain context failed; memory was not loaded."));
    child.stdin.end(JSON.stringify({ cwd, prompt }));
  });

  pi.on("before_agent_start", async (event: any, ctx: any) => {
    lastPrompt = event.prompt || "";
    const content = await load(ctx.cwd, lastPrompt);
    if (content === lastPacket) return;
    lastPacket = content;
    return { message: { customType: "cog-brain-context", content, display: false } };
  });

  // Compaction may happen inside a running task, before another user prompt.
  pi.on("session_compact", async (_event: any, ctx: any) => {
    lastPacket = await load(ctx.cwd, lastPrompt);
    pi.sendMessage({ customType: "cog-brain-context", content: lastPacket, display: false },
                   { triggerTurn: false });
  });
}
