/* Minimal, dependency-free markdown renderer.
 *
 * Everything is HTML-escaped before any markup is produced, so model output
 * can never inject nodes into the page. Supports: fenced code (with copy
 * button), headings, lists, blockquotes, pipe tables, horizontal rules,
 * inline code/bold/italic/strikethrough/links. */
(function (global) {
  "use strict";

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function inline(text) {
    let out = escapeHtml(text);
    const codes = [];
    out = out.replace(/`([^`]+)`/g, function (_, code) {
      codes.push(code);
      return "\u0000" + (codes.length - 1) + "\u0000";
    });
    out = out
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g,
        '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/~~([^~]+)~~/g, "<del>$1</del>");
    return out.replace(/\u0000(\d+)\u0000/g, function (_, index) {
      return "<code>" + codes[Number(index)] + "</code>";
    });
  }

  function tableRow(line) {
    return line.trim().replace(/^\||\|$/g, "").split("|").map(function (cell) {
      return cell.trim();
    });
  }

  function render(source) {
    const lines = String(source == null ? "" : source).split("\n");
    const html = [];
    let index = 0;

    while (index < lines.length) {
      const line = lines[index];

      const fence = line.match(/^\s*```+\s*([\w+#.-]*)\s*$/);
      if (fence) {
        const lang = fence[1] || "";
        const buffer = [];
        index++;
        while (index < lines.length && !/^\s*```+\s*$/.test(lines[index])) {
          buffer.push(lines[index]);
          index++;
        }
        index++;
        html.push(
          '<div class="codeblock"><header><span>' + escapeHtml(lang || "code") +
          '</span><button class="copy-btn" type="button">copy</button></header>' +
          "<pre><code>" + escapeHtml(buffer.join("\n")) + "</code></pre></div>"
        );
        continue;
      }

      if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) {
        html.push("<hr>");
        index++;
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        const level = Math.min(heading[1].length, 6);
        html.push("<h" + level + ">" + inline(heading[2]) + "</h" + level + ">");
        index++;
        continue;
      }

      if (/^\s*>\s?/.test(line)) {
        const buffer = [];
        while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
          buffer.push(lines[index].replace(/^\s*>\s?/, ""));
          index++;
        }
        html.push("<blockquote>" + render(buffer.join("\n")) + "</blockquote>");
        continue;
      }

      if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[index + 1] || "")) {
        const head = tableRow(line);
        index += 2;
        const body = [];
        while (index < lines.length && /^\s*\|.*\|\s*$/.test(lines[index])) {
          body.push(tableRow(lines[index]));
          index++;
        }
        html.push(
          "<table><thead><tr>" +
          head.map(function (c) { return "<th>" + inline(c) + "</th>"; }).join("") +
          "</tr></thead><tbody>" +
          body.map(function (row) {
            return "<tr>" + row.map(function (c) {
              return "<td>" + inline(c) + "</td>";
            }).join("") + "</tr>";
          }).join("") +
          "</tbody></table>"
        );
        continue;
      }

      const bullet = line.match(/^\s*([-*+]|\d+[.)])\s+/);
      if (bullet) {
        const ordered = /\d/.test(bullet[1]);
        const items = [];
        while (index < lines.length) {
          const match = lines[index].match(/^\s*([-*+]|\d+[.)])\s+(.*)$/);
          if (!match) {
            // A wrapped continuation line belongs to the previous bullet.
            if (items.length && /^\s{2,}\S/.test(lines[index])) {
              items[items.length - 1] += " " + lines[index].trim();
              index++;
              continue;
            }
            break;
          }
          items.push(match[2]);
          index++;
        }
        const tag = ordered ? "ol" : "ul";
        html.push("<" + tag + ">" + items.map(function (item) {
          return "<li>" + inline(item) + "</li>";
        }).join("") + "</" + tag + ">");
        continue;
      }

      if (!line.trim()) {
        index++;
        continue;
      }

      const paragraph = [];
      while (index < lines.length && lines[index].trim() &&
             !/^\s*(```|#{1,6}\s|>\s?|\||([-*+]|\d+[.)])\s)/.test(lines[index])) {
        paragraph.push(lines[index]);
        index++;
      }
      if (paragraph.length) {
        html.push("<p>" + inline(paragraph.join("\n")).replace(/\n/g, "<br>") + "</p>");
      } else {
        index++;
      }
    }

    return html.join("");
  }

  global.MD = { render: render, escapeHtml: escapeHtml };
})(window);
