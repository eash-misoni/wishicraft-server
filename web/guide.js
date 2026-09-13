"use strict";

for (const code of document.querySelectorAll("article code")) {
  if (!code.textContent.startsWith("/mc ")) continue;
  const command = code.textContent;
  const group = document.createElement("span");
  group.className = "command";
  code.replaceWith(group);
  group.append(code);
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "コピー";
  button.setAttribute("aria-label", `${command} をコピー`);
  button.addEventListener("click", async () => {
    const feedback = document.querySelector("#copy-feedback");
    feedback.textContent = "";
    try {
      await navigator.clipboard.writeText(command);
      feedback.textContent = `${command} をコピーしました。Discordで確認して送信してください。`;
    } catch {
      feedback.textContent = "コピーできませんでした。コマンドの文字を選択してコピーしてください。";
    }
  });
  group.append(button);
}
