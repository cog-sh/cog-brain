// Native OpenCode V1 adapter. OpenCode V2 uses a different plugin contract.
import { spawn } from "node:child_process";

const python = __PYTHON__;
const keepMcp = __KEEP_MCP__;

export default async function cogBrain(ctx) {
  return {
    config: async config => {
      if (!keepMcp && config.mcp?.["cog-brain"]) config.mcp["cog-brain"].enabled = false;
    },
    "experimental.chat.system.transform": async (_input, output) => {
      const text = await new Promise(resolve => {
        const child = spawn(python, ["-m", "cog_brain.cli", "hook", "--harness", "opencode"],
          { cwd: ctx.directory || process.cwd(), stdio: ["pipe", "pipe", "pipe"] });
        let text = "";
        let done = false;
        const finish = value => { if (!done) { done = true; clearTimeout(timer); resolve(value); } };
        const timer = setTimeout(() => { child.kill("SIGKILL"); finish("cog-brain context timed out."); }, 9000);
        child.stdout.on("data", data => {
          text += data.toString();
          if (text.length > 32000) { child.kill("SIGKILL"); finish("cog-brain output limit exceeded."); }
        });
        child.stderr.resume();
        child.stdin.on("error", () => {});
        child.on("error", () => finish("cog-brain runtime unavailable."));
        child.on("close", code => finish(code === 0 ? text.trim() : "cog-brain context unavailable."));
        child.stdin.end(JSON.stringify({ cwd: ctx.directory || process.cwd() }));
      });
      output.system.push(text);
    },
  };
}
