"""Templates: texts the user writes once and puts into a mail with two clicks."""

import json
import os
import secrets

import ragdoll as R
from .common import fail, text_in


class Templates:
    """Reply templates. (Part of Backend.)"""

    # ---- templates: texts the user writes once and puts into a mail with two clicks

    def templates(self):
        try:
            with open(os.path.join(R.CFG.home, "templates.json"), encoding="utf-8") as f:
                d = json.load(f)
            return [x for x in d if isinstance(x, dict) and x.get("id") and isinstance(x.get("name"), str)]
        except (OSError, ValueError):
            return []

    def api_templates(self, a):
        """list (the default), save {id?, name, html}, delete {id}. Always returns the list."""
        do = a.get("do") or "list"
        with self.preflock:
            items = self.templates()
            if do == "save":
                name, html = text_in(a, "name").strip()[:80], text_in(a, "html")[:200000]
                if not name:
                    fail("Give the template a name.")
                if not R.html_to_text(html).strip():
                    fail("The template is empty.")
                new = {"id": text_in(a, "id") or secrets.token_hex(5), "name": name, "html": html}
                if any(x["id"] == new["id"] for x in items):
                    items = [new if x["id"] == new["id"] else x for x in items]
                else:
                    items.append(new)
            elif do == "delete":
                items = [x for x in items if x["id"] != a.get("id")]
            if do in ("save", "delete"):
                os.makedirs(R.CFG.home, exist_ok=True)
                tmp = os.path.join(R.CFG.home, "templates.json.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(items, f, ensure_ascii=False)
                os.replace(tmp, os.path.join(R.CFG.home, "templates.json"))
        return {"templates": items}
