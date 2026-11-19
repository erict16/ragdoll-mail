// Reply templates in compose.
import { api, t } from "./core.js";
import { fail, menu } from "./ui.js";
import { cleanHTML, edChanged, edFocus } from "./editor.js";
import { openSettings } from "./settings.js";

// A template goes in where the caret is. The list is made in Settings.
export async function templateMenu(anchor) {
  let list;
  try { list = (await api("templates")).templates; } catch (e) { return fail(e); }
  const items = list.map((x) => ({ icon: "file-text", label: x.name, run: () => {
    if (!edFocus()) return;
    document.execCommand("insertHTML", false, cleanHTML(x.html));
    edChanged();
  } }));
  if (items.length) items.push("-");
  items.push({ icon: "settings", label: t(list.length ? "edit_templates" : "new_template"), run: () => openSettings("templates") });
  menu(anchor, items);
}
