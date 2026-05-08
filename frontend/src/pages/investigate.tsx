import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertDialog, Button, Card, Chip, Spinner, TextArea } from "@heroui/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  deleteChildPoints,
  deleteInvestigation,
  getInvestigation,
  getInvestigations,
  processPoint,
  setPoint,
  type InvestigationDetailData,
  type InvestigationSummary,
  type Point,
  type PointStatus,
} from "../lib/api";

const PANEL_WIDTH = 320;
const PANEL_MARGIN = 16;
const DRAFT_NODE_ID = "draft-root";
const NODE_HORIZONTAL_GAP = 460;
const NODE_VERTICAL_GAP = 640;

type DraftPoint = {
  question: string;
  status: "draft";
};

type InvestigationNodeData = {
  point: Point | DraftPoint;
  isDraft: boolean;
  canProcess: boolean;
  isSubmitting: boolean;
  onQuestionChange: (pointId: number | null, question: string) => void;
  onProcess: (pointId: number | null) => void;
};

type PanelPosition = {
  x: number;
  y: number;
};

type NodePositions = Record<string, { x: number; y: number }>;

function investigationLabel(investigation: InvestigationSummary) {
  return (
    investigation.root_question ||
    investigation.investigation_name ||
    `Investigation ${investigation.investigation_id}`
  );
}

function statusColor(status: PointStatus | "draft" | "") {
  if (status === "processing") {
    return "warning";
  }

  if (status === "completed") {
    return "success";
  }

  if (status === "failed") {
    return "danger";
  }

  return "default";
}

function statusLabel(status: PointStatus | "draft" | "") {
  if (!status) {
    return "No status";
  }

  return status.replace("_", " ");
}

function pointTitle(point: Point | DraftPoint, isDraft: boolean) {
  if (isDraft) {
    return "New investigation";
  }

  return "point_type" in point ? point.point_type.replace("_", " ") : "Point";
}

function clampPanelPosition(position: PanelPosition): PanelPosition {
  const maxX = Math.max(PANEL_MARGIN, window.innerWidth - PANEL_WIDTH - PANEL_MARGIN);

  return {
    x: Math.min(Math.max(PANEL_MARGIN, position.x), maxX),
    y: 0,
  };
}

function InvestigationPointNode({ data }: NodeProps<Node<InvestigationNodeData>>) {
  const { point, isDraft, canProcess, isSubmitting, onQuestionChange, onProcess } = data;
  const persistedPoint = "point_id" in point ? point : null;
  const status = isDraft ? "draft" : persistedPoint?.status ?? "";
  const question = point.question;
  const conclusion = persistedPoint?.conclusion.trim() ?? "";
  const reason = persistedPoint?.reason.trim() ?? "";
  const error = persistedPoint?.error.trim() ?? "";
  const rawData = persistedPoint?.raw_data ?? {};
  const hasRawData = Object.keys(rawData).length > 0;

  return (
    <Card className="w-[360px] border border-default-200 bg-background text-left shadow-lg">
      <Handle type="target" position={Position.Top} />
      <Card.Header>
        <div className="w-full">
          <div className="flex w-full items-center justify-between gap-3">
            <Chip color={isDraft ? "default" : "accent"} size="sm" variant="primary">
              {pointTitle(point, isDraft)}
            </Chip>
            <Chip color={statusColor(status)} size="sm" variant="soft">
              {statusLabel(status)}
            </Chip>
          </div>
          {/* <p className="mt-2 text-xs text-default-500">
            {persistedPoint ? `Point #${persistedPoint.point_id}` : "Draft point"}
          </p> */}
        </div>
      </Card.Header>
      <Card.Content className="flex flex-col gap-3">
        {canProcess ? (
          <label className="nodrag flex flex-col gap-1">
            <span className="text-xs font-medium uppercase tracking-normal text-default-500">
              Question
            </span>
            <TextArea
              onChange={(event) =>
                onQuestionChange(persistedPoint?.point_id ?? null, event.target.value)
              }
              placeholder="Enter the investigation question"
              rows={4}
              value={question}
              variant="primary"
            />
          </label>
        ) : (
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-normal text-default-500">
              Question
            </p>
            <p className="whitespace-pre-wrap text-sm text-foreground">
              {question || "No question recorded."}
            </p>
          </div>
        )}

        {reason ? (
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-normal text-default-500">
              Reason
            </p>
            <p className="whitespace-pre-wrap text-sm">{reason}</p>
          </div>
        ) : null}

        {conclusion ? (
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-normal text-default-500">
              Conclusion
            </p>
            <p className="whitespace-pre-wrap text-sm">{conclusion}</p>
          </div>
        ) : null}

        {error ? (
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-normal text-danger">
              Error
            </p>
            <p className="whitespace-pre-wrap text-sm text-danger">{error}</p>
          </div>
        ) : null}

        {hasRawData ? (
          <pre className="max-h-36 overflow-auto rounded-md bg-default-100 p-3 text-xs text-default-700">
            {JSON.stringify(rawData, null, 2)}
          </pre>
        ) : null}
      </Card.Content>
      {canProcess ? (
        <Card.Footer>
          <Button
            className="nodrag w-full"
            isDisabled={!question.trim() || isSubmitting}
            onPress={() => onProcess(persistedPoint?.point_id ?? null)}
            type="button"
            variant="primary"
          >
            {isSubmitting
              ? "Processing"
              : status === "failed" || status === "completed"
                ? "Retry"
                : "Process"}
          </Button>
        </Card.Footer>
      ) : null}
      <Handle type="source" position={Position.Bottom} />
    </Card>
  );
}

function buildPointLayout(points: Point[]): Map<number, { x: number; y: number }> {
  const childrenByParent = new Map<number | null, Point[]>();

  for (const point of points) {
    const parentId = point.parent_point_id ?? null;
    childrenByParent.set(parentId, [...(childrenByParent.get(parentId) ?? []), point]);
  }

  for (const children of childrenByParent.values()) {
    children.sort((left, right) => left.point_id - right.point_id);
  }

  const positions = new Map<number, { x: number; y: number }>();

  function placePoint(point: Point, x: number, depth: number) {
    positions.set(point.point_id, {
      x,
      y: depth * NODE_VERTICAL_GAP,
    });

    const children = childrenByParent.get(point.point_id) ?? [];
    const childrenWidth = (children.length - 1) * NODE_HORIZONTAL_GAP;

    children.forEach((child, index) => {
      placePoint(child, x - childrenWidth / 2 + index * NODE_HORIZONTAL_GAP, depth + 1);
    });
  }

  const roots = childrenByParent.get(null) ?? [];
  const rootsWidth = (roots.length - 1) * NODE_HORIZONTAL_GAP;

  roots.forEach((root, index) => {
    placePoint(root, -rootsWidth / 2 + index * NODE_HORIZONTAL_GAP, 0);
  });

  return positions;
}

function nodePositionKey(graphKey: string, nodeId: string) {
  return `${graphKey}:${nodeId}`;
}

export default function InvestigatePage() {
  const [investigations, setInvestigations] = useState<InvestigationSummary[]>([]);
  const [activeInvestigationId, setActiveInvestigationId] = useState<number | null>(null);
  const [detail, setDetail] = useState<InvestigationDetailData | null>(null);
  const [draftPoint, setDraftPoint] = useState<DraftPoint | null>({ question: "", status: "draft" });
  const [panelPosition, setPanelPosition] = useState<PanelPosition>({ x: 16, y: 0 });
  const [nodePositions, setNodePositions] = useState<NodePositions>({});
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<InvestigationSummary | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const dragOffsetRef = useRef<PanelPosition | null>(null);

  const refreshInvestigations = useCallback(async () => {
    setIsLoadingList(true);

    try {
      setInvestigations(await getInvestigations());
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to load investigations.");
    } finally {
      setIsLoadingList(false);
    }
  }, []);

  const loadInvestigation = useCallback(async (investigationId: number, showLoading = true) => {
    if (showLoading) {
      setIsLoadingDetail(true);
    }

    try {
      const nextDetail = await getInvestigation(investigationId);
      setDetail(nextDetail);
      setActiveInvestigationId(investigationId);
      setDraftPoint(null);
      setErrorMessage("");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to load investigation.");
    } finally {
      if (showLoading) {
        setIsLoadingDetail(false);
      }
    }
  }, []);
  const hasProcessingPoint = detail?.points.some((point) => point.status === "processing") ?? false;

  useEffect(() => {
    void refreshInvestigations();
  }, [refreshInvestigations]);

  useEffect(() => {
    if (activeInvestigationId === null || !hasProcessingPoint) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      void loadInvestigation(activeInvestigationId, false);
      void refreshInvestigations();
    }, 5000);

    return () => window.clearInterval(intervalId);
  }, [activeInvestigationId, hasProcessingPoint, loadInvestigation, refreshInvestigations]);

  useEffect(() => {
    function handlePointerMove(event: PointerEvent) {
      if (!dragOffsetRef.current) {
        return;
      }

      setPanelPosition(
        clampPanelPosition({
          x: event.clientX - dragOffsetRef.current.x,
          y: event.clientY - dragOffsetRef.current.y,
        }),
      );
    }

    function handlePointerUp() {
      dragOffsetRef.current = null;
    }

    function handleResize() {
      setPanelPosition((position) => clampPanelPosition(position));
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  const handlePanelPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      dragOffsetRef.current = {
        x: event.clientX - panelPosition.x,
        y: event.clientY - panelPosition.y,
      };
    },
    [panelPosition],
  );

  const handleNewInvestigation = useCallback(() => {
    setActiveInvestigationId(null);
    setDetail(null);
    setDraftPoint({ question: "", status: "draft" });
    setErrorMessage("");
  }, []);

  const handleSelectInvestigation = useCallback(
    (investigationId: number) => {
      void loadInvestigation(investigationId);
    },
    [loadInvestigation],
  );

  const handleDeleteInvestigation = useCallback(
    async () => {
      if (!deleteTarget) {
        return;
      }

      setIsLoadingList(true);
      setErrorMessage("");

      try {
        await deleteInvestigation(deleteTarget.investigation_id);
        if (deleteTarget.investigation_id === activeInvestigationId) {
          setActiveInvestigationId(null);
          setDetail(null);
          setDraftPoint({ question: "", status: "draft" });
        }
        setDeleteTarget(null);
        await refreshInvestigations();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Failed to delete investigation.");
      } finally {
        setIsLoadingList(false);
      }
    },
    [activeInvestigationId, deleteTarget, refreshInvestigations],
  );

  const handleQuestionChange = useCallback((pointId: number | null, question: string) => {
    if (pointId === null) {
      setDraftPoint((current) => (current ? { ...current, question } : current));
      return;
    }

    setDetail((current) => {
      if (!current) {
        return current;
      }

      return {
        ...current,
        points: current.points.map((point) =>
          point.point_id === pointId ? { ...point, question } : point,
        ),
      };
    });
  }, []);

  const handleProcess = useCallback(
    async (pointId: number | null) => {
      const draftQuestion =
        pointId === null
          ? draftPoint?.question.trim()
          : detail?.points.find((point) => point.point_id === pointId)?.question.trim();

      if (!draftQuestion) {
        return;
      }

      setIsSubmitting(true);
      setErrorMessage("");

      try {
        const point = await setPoint({
          investigation_id: activeInvestigationId,
          point_id: pointId,
          question: draftQuestion,
          conclusion: "",
        });
        if (pointId !== null) {
          await deleteChildPoints(point.point_id);
        }
        const processResult = await processPoint(point.point_id);
        const investigationId = processResult.investigation_id ?? point.investigation_id;

        if (investigationId !== null) {
          await loadInvestigation(investigationId);
        }

        await refreshInvestigations();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Failed to process point.");
      } finally {
        setIsSubmitting(false);
      }
    },
    [activeInvestigationId, detail, draftPoint, loadInvestigation, refreshInvestigations],
  );

  const nodeTypes = useMemo(() => ({ investigationPoint: InvestigationPointNode }), []);
  const graphKey = draftPoint
    ? "draft"
    : activeInvestigationId !== null
      ? `investigation-${activeInvestigationId}`
      : "empty";

  const handleNodesChange = useCallback(
    (changes: NodeChange<Node<InvestigationNodeData>>[]) => {
      setNodePositions((current) => {
        let next = current;

        for (const change of changes) {
          if (change.type !== "position" || !change.position) {
            continue;
          }

          if (next === current) {
            next = { ...current };
          }

          next[nodePositionKey(graphKey, change.id)] = change.position;
        }

        return next;
      });
    },
    [graphKey],
  );

  const nodes = useMemo<Node<InvestigationNodeData>[]>(() => {
    if (draftPoint) {
      const nodeId = DRAFT_NODE_ID;

      return [
        {
          id: nodeId,
          type: "investigationPoint",
          position: nodePositions[nodePositionKey(graphKey, nodeId)] ?? { x: 0, y: 0 },
          data: {
            point: draftPoint,
            isDraft: true,
            canProcess: true,
            isSubmitting,
            onQuestionChange: handleQuestionChange,
            onProcess: handleProcess,
          },
        },
      ];
    }

    const points = detail?.points ?? [];
    const positions = buildPointLayout(points);

    return points.map((point) => ({
      id: String(point.point_id),
      type: "investigationPoint",
      position:
        nodePositions[nodePositionKey(graphKey, String(point.point_id))] ??
        positions.get(point.point_id) ??
        { x: 0, y: 0 },
      data: {
        point,
        isDraft: false,
        canProcess: point.status !== "processing",
        isSubmitting,
        onQuestionChange: handleQuestionChange,
        onProcess: handleProcess,
      },
    }));
  }, [
    detail,
    draftPoint,
    graphKey,
    handleProcess,
    handleQuestionChange,
    isSubmitting,
    nodePositions,
  ]);

  const edges = useMemo<Edge[]>(() => {
    const points = detail?.points ?? [];

    return points
      .filter((point) => point.parent_point_id !== null)
      .map((point) => ({
        id: `${point.parent_point_id}-${point.point_id}`,
        source: String(point.parent_point_id),
        target: String(point.point_id),
      }));
  }, [detail]);

  const selectedSummary = investigations.find(
    (investigation) => investigation.investigation_id === activeInvestigationId,
  );

  return (
    <main className="fixed inset-0 bg-default-50 text-left">
      <ReactFlow
        className="bg-default-50"
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        key={draftPoint ? DRAFT_NODE_ID : activeInvestigationId}
        nodeTypes={nodeTypes}
        nodes={nodes}
        nodesDraggable
        onNodesChange={handleNodesChange}
      >
        <Background />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>

      <Card
        className="absolute z-20 flex h-dvh w-[320px] flex-col border border-default-200 bg-background/95 shadow-xl backdrop-blur"
        style={{ left: panelPosition.x, top: panelPosition.y }}
      >
        <Card.Header
          className="cursor-move select-none border-b border-default-200"
          onPointerDown={handlePanelPointerDown}
        >
          <div className="flex w-full items-center justify-between gap-3">
            <div>
              <Card.Description>Workspace</Card.Description>
              <Card.Title className="text-lg">Investigations</Card.Title>
            </div>
            {isLoadingList ? <Spinner size="sm" /> : null}
          </div>
        </Card.Header>
        <Card.Content className="min-h-0 flex-1 overflow-hidden p-0">
          <div className="border-b border-default-200 p-3">
            <Button className="w-full" onPress={handleNewInvestigation} type="button" variant="primary">
              New Investigation
            </Button>
          </div>

          {errorMessage ? (
            <div className="border-b border-danger-100 bg-danger-50 p-3 text-sm text-danger">
              {errorMessage}
            </div>
          ) : null}

          <div className="h-full overflow-auto p-2">
            {investigations.length === 0 && !isLoadingList ? (
              <p className="p-3 text-sm text-default-500">No previous investigations.</p>
            ) : null}

            {investigations.map((investigation) => {
              const isSelected = investigation.investigation_id === activeInvestigationId;
              const label = investigationLabel(investigation);

              return (
                <div
                  className={`mb-2 w-full rounded-lg border p-3 text-left transition ${
                    isSelected
                      ? "border-primary bg-primary-50 text-primary"
                      : "border-transparent bg-default-50 text-foreground hover:border-default-200 hover:bg-default-100"
                  }`}
                  key={investigation.investigation_id}
                >
                  <button
                    className="block w-full text-left"
                    onClick={() => handleSelectInvestigation(investigation.investigation_id)}
                    type="button"
                  >
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-default-500">
                        #{investigation.investigation_id}
                      </span>
                      <Chip
                        color={statusColor(investigation.root_status)}
                        size="sm"
                        variant="soft"
                      >
                        {statusLabel(investigation.root_status)}
                      </Chip>
                    </div>
                    <p className="line-clamp-2 text-sm font-medium">{label}</p>
                    <p className="mt-2 text-xs text-default-500">
                      {investigation.point_count} point{investigation.point_count === 1 ? "" : "s"}
                    </p>
                  </button>
                  <div className="mt-3 flex justify-end">
                    <Button
                      isDisabled={isLoadingList}
                      onPress={() => setDeleteTarget(investigation)}
                      size="sm"
                      type="button"
                      variant="danger-soft"
                    >
                      Delete
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </Card.Content>
      </Card>

      {deleteTarget ? (
        <AlertDialog
          isOpen
          onOpenChange={(isOpen) => {
            if (!isOpen && !isLoadingList) {
              setDeleteTarget(null);
            }
          }}
        >
          <AlertDialog.Backdrop>
            <AlertDialog.Container placement="center" size="md">
              <AlertDialog.Dialog>
                <AlertDialog.Header>
                  <AlertDialog.Icon status="danger" />
                  <AlertDialog.Heading>Delete investigation</AlertDialog.Heading>
                </AlertDialog.Header>
                <AlertDialog.Body>
                  <p className="text-sm text-default-600">
                    Delete "{investigationLabel(deleteTarget)}" and all of its points? This cannot
                    be undone.
                  </p>
                </AlertDialog.Body>
                <AlertDialog.Footer>
                  <Button
                    isDisabled={isLoadingList}
                    onPress={() => setDeleteTarget(null)}
                    type="button"
                    variant="secondary"
                  >
                    Cancel
                  </Button>
                  <Button
                    isDisabled={isLoadingList}
                    onPress={() => void handleDeleteInvestigation()}
                    type="button"
                    variant="danger"
                  >
                    {isLoadingList ? "Deleting" : "Delete"}
                  </Button>
                </AlertDialog.Footer>
              </AlertDialog.Dialog>
            </AlertDialog.Container>
          </AlertDialog.Backdrop>
        </AlertDialog>
      ) : null}

      <div className="pointer-events-none absolute right-4 top-4 z-10 flex items-center gap-2 rounded-lg border border-default-200 bg-background/90 px-3 py-2 text-sm shadow-sm backdrop-blur">
        {isLoadingDetail ? <Spinner size="sm" /> : null}
        <span className="text-default-600">
          {draftPoint
            ? "Draft investigation"
            : selectedSummary?.root_question ||
              detail?.investigation.investigation_name ||
              "Select an investigation"}
        </span>
      </div>
    </main>
  );
}
