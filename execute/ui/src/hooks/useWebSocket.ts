import { useEffect, useRef } from 'react';
import type { ExecutionWsMessage } from '../types/models';

export function useWebSocket(onMessage: (msg: ExecutionWsMessage) => void) {
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
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/execute`);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          onMessageRef.current(JSON.parse(event.data));
        } catch (error) {
          console.error('Failed to parse execute WS message', error);
        }
      };

      ws.onopen = () => {
        ws.send('ping');
      };

      ws.onclose = () => {
        if (!isActive) {
          return;
        }
        timeoutId = setTimeout(connect, 2000);
      };

      ws.onerror = (error) => {
        console.error('Execute WebSocket error', error);
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
