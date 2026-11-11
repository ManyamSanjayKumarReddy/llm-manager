import type { AnchorHTMLAttributes, MouseEvent } from "react";

import { navigate } from "./router";

interface Props extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> {
  to: string;
}

/**
 * A normal link (it can be opened in a new tab, copied or middle-clicked) that moves around the app
 * without reloading the page when you click it.
 */
export function Link({ to, onClick, ...rest }: Props) {
  function click(event: MouseEvent<HTMLAnchorElement>) {
    onClick?.(event);
    const modified = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
    if (event.defaultPrevented || event.button !== 0 || modified || rest.target === "_blank") return;
    event.preventDefault();
    navigate(to);
  }
  return <a {...rest} href={to} onClick={click} />;
}
