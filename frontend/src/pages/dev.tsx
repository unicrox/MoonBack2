import { Button, Card, Chip } from "@heroui/react";
import { useCallback, useEffect, useState } from "react";
import {
  API_BASE_URL,
  apiRequest,
  getFrontendConsts,
  getFrontendConstsHash,
} from "../lib/api";

type ConnectionStatus = "checking" | "online" | "offline";
type FrontendConsts = ReturnType<typeof getFrontendConsts>;

export default function DevPage() {
  const [status, setStatus] = useState<ConnectionStatus>("checking");
  const [message, setMessage] = useState("Checking backend connection...");
  const [constHash, setConstHash] = useState<string | null>(getFrontendConstsHash);
  const [frontendConsts, setFrontendConsts] = useState<FrontendConsts>(getFrontendConsts);

  const checkBackendConnection = useCallback(async () => {
    setStatus("checking");
    setMessage("Checking backend connection...");

    try {
      const response = await apiRequest("/ping");

      if (response.message !== "pong") {
        throw new Error(`Unexpected response: ${response.message ?? "No message"}`);
      }

      setConstHash(getFrontendConstsHash());
      setFrontendConsts(getFrontendConsts());
      setStatus("online");
      setMessage("Backend is online. Frontend constants are up to date.");
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
  const hasFrontendConsts = Object.keys(frontendConsts).length > 0;

  return (
    <main className="flex min-h-screen flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-2xl">
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
          <div className="mb-6 flex flex-col gap-2">
            <code>{API_BASE_URL}/ping</code>
            <code>const hash: {constHash ?? "not loaded"}</code>
          </div>
          <div>
            <p className="mb-2 text-sm font-medium">Latest constants</p>
            <pre className="max-h-72 overflow-auto rounded-lg bg-default p-4 text-left text-sm">
              {hasFrontendConsts
                ? JSON.stringify(frontendConsts, null, 2)
                : "No constants loaded yet."}
            </pre>
          </div>
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
