// The parsed CV waiting to be reviewed on the Add candidate page. Kept in memory (not the URL); it holds personal data.
import { api } from "./api.js";
import { h, button, toast, errormessage, can, state } from "./ui.js";
import { go } from "./router.js";

const MAX_BYTES = 5 * 1024 * 1024;
let draft = null;

export const takeCvDraft = () => { const d = draft; draft = null; return d; };

export const canParseCv = () => can.write() && !!state.meta?.ai_enabled;

// A button that reads a CV with AI and opens the Add candidate form pre-filled with what it found.
export function uploadCvButton(text = "Upload CV", cls = "") {
  const input = h("input", { type: "file", accept: ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document", hidden: true });
  const btn = button(text, () => input.click(), cls);
  input.addEventListener("change", async () => {
    const file = input.files[0];
    input.value = "";
    if (!file) return;
    if (file.size > MAX_BYTES) { toast("The CV must be smaller than 5 MB.", "error"); return; }
    btn.disabled = true;
    btn.textContent = "Reading CV...";
    try {
      draft = await api.upload("/cv/parse?filename=" + encodeURIComponent(file.name), await file.arrayBuffer());
      go("/candidate/new?x=" + Date.now());
    } catch (e) {
      toast(e.errors?.file || errormessage(e), "error", 8000);
    } finally {
      btn.disabled = false;
      btn.textContent = text;
    }
  });
  return h("span", null, btn, input);
}