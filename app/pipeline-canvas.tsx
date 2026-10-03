"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Background, BackgroundVariant, BaseEdge, EdgeLabelRenderer, Handle,
  MarkerType, Position, ReactFlow, ReactFlowProvider, getBezierPath, useNodesInitialized, useReactFlow, useStore,
  type Edge, type EdgeProps, type Node, type NodeChange, type NodeProps,
} from "@xyflow/react";
import {
  AlertCircle, ArrowRight, Braces, BrainCircuit, Database, FileInput, FileOutput, FileText,
  Focus, Grip, Image, LayoutTemplate, Maximize2, Minimize2, Plus, ScanText,
  SlidersHorizontal, Sparkles, WandSparkles, ZoomIn, ZoomOut,
  type LucideIcon,
} from "lucide-react";
import "@xyflow/react/dist/style.css";

import { pipelineFlow, stepProblems, type FlowCategory } from "../lib/pipeline-flow";
import { summarizeStep } from "../lib/pipeline-editor";
import type { ArtifactSummary, PipelineStep, ProcessorRecord, StepCatalogueEntry, StepKind } from "../lib/types";
import { InfoHint } from "./info-hint";

export const STEP_ICONS: Record<StepKind, LucideIcon> = {
  render_pages: Image, read_pdf_text: FileText, document_ai_ocr: ScanText,
  document_ai_layout: LayoutTemplate, document_ai_extract: Sparkles,
  llm_extract: WandSparkles, regex_refine: Braces, master_data_lookup: Database,
  supplier_rules: SlidersHorizontal, artifact_predict: BrainCircuit,
};

type CardData = {
  label: string; summary: string; detail?: string; category: FlowCategory;
  kind?: StepKind; index: number | null; conditional?: boolean; problems: string[];
};
type FlowNode = Node<CardData, "step">;
type FlowEdge = Edge<{ insertAt: number; onInsert: (at: number) => void; disabled: boolean }, "insert">;

function StepNode({ data, selected }: NodeProps<FlowNode>) {
  const terminal = data.index === null;
  const Icon = data.kind ? STEP_ICONS[data.kind] : data.label === "PDF document" ? FileInput : FileOutput;
  return (
    <div className={`pipeline-node ${terminal ? "terminal" : ""} tone-${data.category} ${selected ? "is-selected" : ""} ${data.problems.length ? "has-problem" : ""}`}>
      {data.label !== "PDF document" && <Handle type="target" position={Position.Left} isConnectable={false} />}
      <div className="pipeline-node-top">
        <span className="pipeline-node-icon"><Icon size={21} /></span>
        {!terminal && <span className="pipeline-node-number">STEP {Number(data.index) + 1}</span>}
        {data.problems.length > 0 && <AlertCircle size={15} className="pipeline-node-error" aria-label="Step needs attention" />}
      </div>
      <strong>{data.label}</strong>
      <p>{data.summary}</p>
      {data.detail && <span className="pipeline-node-detail" title={data.detail}>{data.detail}</span>}
      {data.conditional && <span className="pipeline-node-condition">Only PDFs without text</span>}
      {data.label !== "Extracted fields" && <Handle type="source" position={Position.Right} isConnectable={false} />}
    </div>
  );
}

function InsertEdge(props: EdgeProps<FlowEdge>) {
  const [path, x, y] = getBezierPath(props);
  return <>
    <BaseEdge id={props.id} path={path} markerEnd={props.markerEnd} style={props.style} />
    <EdgeLabelRenderer>
      <button
        className="pipeline-edge-add nodrag nopan"
        style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
        aria-label={`Insert step at position ${(props.data?.insertAt ?? 0) + 1}`}
        title="Insert a step here"
        disabled={props.data?.disabled}
        onClick={() => props.data?.onInsert(props.data.insertAt)}
      ><Plus size={13} /></button>
    </EdgeLabelRenderer>
  </>;
}

const nodeTypes = { step: StepNode };
const edgeTypes = { insert: InsertEdge };

type Props = {
  steps: PipelineStep[]; catalogue: StepCatalogueEntry[]; processors: ProcessorRecord[];
  artifacts: ArtifactSummary[]; model: string; problems: string[]; selectedIndex: number | null; disabled: boolean;
  onSelect: (index: number | null) => void; onInsert: (at: number) => void;
};

function Canvas({ steps, catalogue, processors, artifacts, model, problems, selectedIndex, disabled, onSelect, onInsert }: Props) {
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [measurements, setMeasurements] = useState<Record<string, { width: number; height: number }>>({});
  const [expanded, setExpanded] = useState(false);
  const { fitView, zoomIn, zoomOut, setCenter, getNode } = useReactFlow<FlowNode, FlowEdge>();
  const initialized = useNodesInitialized();
  const canvasWidth = useStore(store => store.width);
  const canvasHeight = useStore(store => store.height);
  const graph = useMemo(() => pipelineFlow(steps), [steps]);
  const nodes: FlowNode[] = graph.nodes.map((node, i) => {
    const step = node.index === null ? null : steps[node.index];
    const processor = step ? processors.find(p => p.id === step.config.processor_ref) : null;
    let detail: string | undefined;
    if (step?.kind === "llm_extract") detail = model || "Choose a model in LLM";
    if (step?.kind === "artifact_predict") {
      const chosen = artifacts.find(artifact => artifact.id === step.config.artifact_id);
      detail = chosen ? `${chosen.name} · ${chosen.id.slice(0, 8)}` : step.config.artifact_id ? "Unavailable model" : "Choose a trained model";
    }
    if (step?.kind.startsWith("document_ai_")) {
      const name = processor?.name || (step.config.processor_ref ? "Unavailable processor" : "Existing processor binding");
      detail = `${name} · ${String(step.config.processor_version || "Processor default")}`;
    }
    return {
      id: node.id, type: "step", position: positions[node.id] ?? { x: i === 0 ? 0 : 220 + (i - 1) * 288, y: 135 },
      measured: measurements[node.id],
      selected: node.index !== null && selectedIndex === node.index,
      draggable: !disabled, selectable: node.index !== null,
      focusable: node.index !== null, ariaRole: node.index !== null ? "button" : "group",
      ariaLabel: node.index === null ? node.label : `Step ${node.index + 1}: ${node.label}. Select to configure.`,
      data: {
        ...node, kind: step?.kind, label: catalogue.find(c => c.kind === step?.kind)?.label ?? node.label,
        summary: step ? summarizeStep(step) : node.id === "input" ? "Start with a PDF" : "Ready for review and scoring",
        detail, problems: node.index === null ? [] : stepProblems(problems, node.index),
      },
    };
  });
  const edges: FlowEdge[] = graph.edges.map(edge => ({
    ...edge, type: "insert", selectable: false,
    data: { insertAt: edge.insertAt, onInsert, disabled },
    style: { stroke: "var(--line-strong)", strokeWidth: 2 },
    markerEnd: { type: MarkerType.ArrowClosed, color: "var(--line-strong)", width: 16, height: 16 },
  }));

  // Selecting a step narrows the canvas to make room for its inspector. Wait
  // for measured nodes so both newly inserted and existing steps stay in view.
  useEffect(() => {
    if (!initialized || !canvasWidth || !canvasHeight) return;
    const frame = window.requestAnimationFrame(() => {
      if (selectedIndex === null) {
        void fitView({ padding: .14, maxZoom: .9, duration: 220 });
        return;
      }
      const node = getNode(`step-${selectedIndex}`);
      if (node) void setCenter(node.position.x + 118, node.position.y + 90, { zoom: .9, duration: 220 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [initialized, selectedIndex, canvasWidth, canvasHeight, getNode, setCenter, fitView]);

  function changed(changes: NodeChange<FlowNode>[]) {
    const resized = changes.filter(change => change.type === "dimensions" && change.dimensions);
    if (resized.length) setMeasurements(previous => {
      const next = { ...previous };
      let updated = false;
      for (const change of resized) if (change.type === "dimensions" && change.dimensions) {
        if (next[change.id]?.width !== change.dimensions.width || next[change.id]?.height !== change.dimensions.height) {
          next[change.id] = change.dimensions;
          updated = true;
        }
      }
      return updated ? next : previous;
    });
    const moved = changes.filter(change => change.type === "position" && change.position);
    if (moved.length) setPositions(previous => {
      const next = { ...previous };
      for (const change of moved) if (change.type === "position" && change.position) next[change.id] = change.position;
      return next;
    });
    // A pointer drag selects a node too. Opening the inspector from that
    // event would resize and recenter the canvas underneath the drag.
  }

  return <div className={`pipeline-canvas ${expanded ? "expanded" : ""}`}>
    <div className="pipeline-canvas-toolbar">
      <span><WorkflowIcon /><strong>Flow</strong><small>{steps.length} {steps.length === 1 ? "step" : "steps"}</small><InfoHint text="Connections follow the numbered execution order. Drag nodes to arrange the canvas; use Earlier or Later in a step's settings to change its execution order. Use the order strip below to select and centre any step." /></span>
      <div>
        <button className="secondary-button small" disabled={disabled} onClick={() => onInsert(steps.length)}><Plus size={14} /> Add step</button>
        <button className="icon-button neutral" title="Restore the execution order layout" aria-label="Arrange nodes" onClick={() => { setPositions({}); window.requestAnimationFrame(() => void fitView({ padding: .18, duration: 250, minZoom: .25, maxZoom: 1 })); }}><Grip size={15} /></button>
        <button className="icon-button neutral" title="Fit the entire pipeline" aria-label="Fit pipeline" onClick={() => void fitView({ padding: .18, duration: 250 })}><Focus size={15} /></button>
        <button className="icon-button neutral" title={expanded ? "Reduce canvas" : "Expand canvas"} aria-label={expanded ? "Reduce canvas" : "Expand canvas"} onClick={() => setExpanded(!expanded)}>{expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}</button>
      </div>
    </div>
    <div className="pipeline-canvas-surface">
      <ReactFlow<FlowNode, FlowEdge>
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
        onNodesChange={changed} onNodeClick={(_, node) => onSelect(node.data.index)}
        onKeyDownCapture={event => {
          if (event.key !== "Enter" && event.key !== " ") return;
          const element = event.target instanceof Element ? event.target.closest(".react-flow__node") : null;
          const index = graph.nodes.find(node => node.id === element?.getAttribute("data-id"))?.index;
          if (index !== undefined && index !== null) {
            event.preventDefault();
            event.stopPropagation();
            onSelect(index);
          }
        }}
        nodesConnectable={false} edgesFocusable={false} deleteKeyCode={null}
        onPaneClick={() => onSelect(null)} fitView fitViewOptions={{ padding: .14, minZoom: .2, maxZoom: .9 }}
        minZoom={.2} maxZoom={1.5} panOnScroll selectionOnDrag={false}
        zoomOnScroll={false} zoomOnPinch zoomOnDoubleClick={false}
        proOptions={{ hideAttribution: true }}
        ariaLabelConfig={{ "node.a11yDescription.default": "Press Enter to select a step. Arrow keys move its position on the canvas, without changing execution order." }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="var(--line-strong)" />
      </ReactFlow>
      <div className="pipeline-zoom-controls">
        <button aria-label="Zoom out" title="Zoom out" onClick={() => void zoomOut({ duration: 160 })}><ZoomOut size={17} /></button>
        <button aria-label="Zoom in" title="Zoom in" onClick={() => void zoomIn({ duration: 160 })}><ZoomIn size={17} /></button>
      </div>
      <div className="pipeline-canvas-help">Drag the canvas to pan · Select a step to configure</div>
    </div>
    <nav className="pipeline-outline" aria-label="Pipeline execution order">
      <span>ORDER</span>
      {steps.length === 0 && <small>Add the first step using a + on the flow.</small>}
      {steps.map((step, index) => <button key={index} className={selectedIndex === index ? "selected" : ""} onClick={() => {
        onSelect(index);
        const position = positions[`step-${index}`] ?? { x: 220 + index * 288, y: 135 };
        void setCenter(position.x + 118, position.y + 85, { zoom: .9, duration: 250 });
      }}><b>{index + 1}</b>{catalogue.find(c => c.kind === step.kind)?.label ?? step.kind}<ArrowRight size={12} /></button>)}
    </nav>
  </div>;
}

function WorkflowIcon() { return <SlidersHorizontal size={15} />; }

export function PipelineCanvas(props: Props) {
  return <ReactFlowProvider><Canvas {...props} /></ReactFlowProvider>;
}
