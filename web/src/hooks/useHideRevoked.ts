import { useState } from "react";

const STORAGE_KEY = "wakeful.keys.hideRevoked";

function read(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

/** The "Hide revoked" choice for API keys, remembered in this browser and shared by every page that lists keys. */
export function useHideRevoked(): [boolean, (on: boolean) => void] {
  const [hide, setHide] = useState(read);
  function change(on: boolean) {
    setHide(on);
    try {
      window.localStorage.setItem(STORAGE_KEY, on ? "1" : "0");
    } catch {
      // The choice just isn't remembered.
    }
  }
  return [hide, change];
}
