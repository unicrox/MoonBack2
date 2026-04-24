import { Button, Card, Chip } from "@heroui/react";
import { useCallback, useEffect, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8200";

type ConnectionStatus = "checking" | "online" | "offline";

export default function DevPage() {
  const [status, setStatus] = useState<ConnectionStatus>("checking");
  const [message, setMessage] = useState("Checking backend connection...");

  const checkBackendConnection = useCallback(async () => {
    setStatus("checking");
    setMessage("Checking backend connection...");

    try {
      const response = await fetch(`${API_BASE_URL}/ping`);
      const text = await response.text();

      if (!response.ok || text !== "pong") {
        throw new Error(`Unexpected response: ${response.status} ${text}`);
      }

      setStatus("online");
      setMessage("Backend is online.");
    } catch (error) {
      setStatus("offline");
      setMessage(error instanceof Error ? error.message : "Backend is offline.");
    }
  }, []);

  useEffect(() => {
    void checkBackendConnection();
  }, [checkBackendConnection]);

  const statusLabel = {
    checking: "Checking",
    online: "Online",
    offline: "Offline",
  }[status];

  const statusColor = {
    checking: "warning",
    online: "success",
    offline: "danger",
  }[status] as "warning" | "success" | "danger";

  return (
    <main className="flex min-h-screen flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-xl">
        <Card.Header>
          <div className="flex w-full flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <Card.Description>Backend connection</Card.Description>
              <Card.Title>{status === "online" ? "Connected" : "Not connected"}</Card.Title>
            </div>
            <Chip color={statusColor} variant="soft">
              {statusLabel}
            </Chip>
          </div>
        </Card.Header>
        <Card.Content>
          <p className="mb-6">{message}</p>
          <code>{API_BASE_URL}/ping</code>
        </Card.Content>
        <Card.Footer>
          <Button
            isDisabled={status === "checking"}
            onPress={checkBackendConnection}
            type="button"
            variant="primary"
          >
            Test again
          </Button>
        </Card.Footer>
      </Card>
    </main>
  );
}
