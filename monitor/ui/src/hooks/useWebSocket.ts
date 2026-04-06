import { useEffect, useRef } from 'react';
import type { MonitorWsMessage } from '../types/models';

export function useWebSocket(onMessage: (msg: MonitorWsMessage) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    let isActive = true;
    let timeoutId: ReturnType<typeof setTimeout>;

    function connect() {
      if (!isActive) {
        return;
      }
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/monitor`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          onMessageRef.current(payload);
        } catch (e) {
          console.error('Failed to parse WS message', e);
        }
      };

      ws.onclose = () => {
        if (!isActive) {
          return;
        }
        timeoutId = setTimeout(connect, 2000);
      };

      ws.onerror = (err) => {
        console.error('WebSocket error:', err);
        ws.close();
      };
    }

    connect();

    return () => {
      isActive = false;
      clearTimeout(timeoutId);
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);
}
