import { useCallback, useEffect, useRef } from "react";
import type { Dispatch } from "react";
import type { Action } from "./state";
import type { ClientMessage } from "./types";
import { wsUrl } from "./config";

/** One websocket to the FastAPI server, with automatic reconnect (the server resends a snapshot on every connect). */
export function useSocket(dispatch: Dispatch<Action>) {
  const ref = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let retry = 0;
    let timer: number | undefined;
    const connect = () => {
      const ws = new WebSocket(wsUrl());
      ref.current = ws;
      ws.onopen = () => { retry = 0; dispatch({ type: "conn", connected: true }); };
      ws.onclose = () => {
        dispatch({ type: "conn", connected: false });
        if (!closed) timer = window.setTimeout(connect, Math.min(1000 * 2 ** retry++, 8000));
      };
      ws.onmessage = (e) => dispatch({ type: "msg", m: JSON.parse(e.data) });
    };
    connect();
    return () => { closed = true; window.clearTimeout(timer); ref.current?.close(); };
  }, [dispatch]);

  return useCallback((msg: ClientMessage): boolean => {
    const ws = ref.current;
    if (ws && ws.readyState === WebSocket.OPEN) { ws.send(JSON.stringify(msg)); return true; }
    return false;
  }, []);
}
