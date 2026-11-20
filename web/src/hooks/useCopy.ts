import { useState } from "react";

/** Copies text and says so for two seconds. Browsers may block the clipboard: the text stays selectable. */
export function useCopy(): [boolean, (text: string) => Promise<void>] {
  const [copied, setCopied] = useState(false);
  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => { setCopied(false); }, 2000);
    } catch {
      // clipboard blocked: nothing to do
    }
  }
  return [copied, copy];
}
