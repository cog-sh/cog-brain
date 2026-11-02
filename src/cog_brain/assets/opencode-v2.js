// Native OpenCode V2 integration; the Python runtime is supplied by installation.
import { spawn } from "node:child_process";
import legacy from "./v1.js";

const python = __PYTHON__;
const keepMcp = __KEEP_MCP__;

function context(cwd, prompt) {
  return new Promise(resolve => {
    const child = spawn(python, ["-m", "cog_brain.cli", "hook", "--harness", "opencode"],
      { cwd, stdio: ["pipe", "pipe", "pipe"] });
    let text = "";
    let settled = false;
    const finish = value => { if (!settled) { settled = true; clearTimeout(timer); resolve(value); } };
    const timer = setTimeout(() => { child.kill("SIGKILL"); finish("cog-brain context timed out."); }, 9000);
    child.stdout.on("data", data => {
      text += data.toString();
      if (text.length > 32000) { child.kill("SIGKILL"); finish("cog-brain context exceeded output limit."); }
    });
    child.stderr.resume();
    child.stdin.on("error", () => {});
    child.on("error", () => finish("cog-brain could not start; install the local runtime."));
    child.on("close", code => finish(code === 0 ? text.trim() : "cog-brain context unavailable."));
    child.stdin.end(JSON.stringify({ cwd, prompt }));
  });
}

export default {
  id: "cog-brain",
  // OpenCode 1.18.29+ accepts a definition and invokes its server factory.
  async server(ctx) { return legacy(ctx || { directory: process.cwd() }); },
  async setup(ctx) {
    if (!keepMcp && ctx.mcp?.transform) {
      await ctx.mcp.transform(editor => {
        if (editor.get("cog-brain")) editor.update("cog-brain", server => { server.disabled = true; });
      });
    }
    await ctx.session.hook("context", async event => {
      const last = [...(event.messages || [])].reverse().find(message => message.role === "user");
      const prompt = typeof last?.content === "string" ? last.content :
        (last?.content || []).filter(part => part.type === "text").map(part => part.text).join("\n");
      event.system.push({ type: "text", text: await context(ctx.location?.directory || ctx.directory || process.cwd(), prompt) });
    });
  },
};
