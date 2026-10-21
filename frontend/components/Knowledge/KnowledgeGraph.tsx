'use client';

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { getSupabaseClient } from '@/lib/supabase/client';

import { API_BASE_URL, API_ENDPOINTS } from '@/lib/constants';

interface Node {
  id: string;
  name: string;
  type: string;
  description?: string;
  properties?: any;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

interface Edge {
  id: string;
  from_node_id: string;
  to_node_id: string;
  type: string;
}

interface GraphData {
  nodes: Node[];
  edges: Edge[];
  stats: {
    node_count: number;
    edge_count: number;
  };
}

interface KnowledgeGraphProps {
  twinId: string;
  onNodeSelect?: (node: Node) => void;
}

// Color mapping for node types
const NODE_COLORS: Record<string, string> = {
  source: '#2563EB',    // blue-500
  chunk: '#0EA5E9',     // violet-500
  concept: '#10b981',   // emerald-500
  person: '#f472b6',    // pink-400
  company: '#3b82f6',   // blue-500
  thesis: '#10b981',    // emerald-500
  topic: '#f59e0b',     // amber-500
  default: '#64748b',   // slate-500
};

// Get color for node type
function getNodeColor(type: string): string {
  const normalizedType = type?.toLowerCase() || 'default';
  for (const [key, color] of Object.entries(NODE_COLORS)) {
    if (normalizedType.includes(key)) return color;
  }
  return NODE_COLORS.default;
}

// Simple force-directed graph simulation
function useForceSimulation(nodes: Node[], edges: Edge[], width: number, height: number) {
  const [simulatedNodes, setSimulatedNodes] = useState<Node[]>([]);
  const animationRef = useRef<number | undefined>(undefined);
  const nodesRef = useRef<Node[]>([]);

  useEffect(() => {
    if (nodes.length === 0) {
      nodesRef.current = [];
      setSimulatedNodes([]);
      return;
    }
    
    // Initialize node positions in a circle
    const initializedNodes = nodes.map((node, i) => ({
      ...node,
      x: width / 2 + Math.cos((i / Math.max(1, nodes.length)) * 2 * Math.PI) * 150,
      y: height / 2 + Math.sin((i / Math.max(1, nodes.length)) * 2 * Math.PI) * 150,
      vx: 0,
      vy: 0,
    }));
    nodesRef.current = initializedNodes;
    setSimulatedNodes(initializedNodes);
  }, [nodes, width, height]);

  useEffect(() => {
    if (nodesRef.current.length === 0) return;

    const centerX = width / 2;
    const centerY = height / 2;

    const simulate = () => {
      const nodeArray = nodesRef.current;
      const k = 150; // Ideal length of edges
      const c = 0.05; // Spring constant
      const repulsion = 2000; // Repulsion force
      const damping = 0.9; // Velocity damping
      const centerForce = 0.01; // Pull to center

      // Apply forces
      for (let i = 0; i < nodeArray.length; i++) {
        const node = nodeArray[i];
        if (!node.x || !node.y) continue;

        // Repulsion between nodes
        for (let j = i + 1; j < nodeArray.length; j++) {
          const other = nodeArray[j];
          if (!other.x || !other.y) continue;

          const dx = node.x - other.x;
          const dy = node.y - other.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = repulsion / (dist * dist);

          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;

          node.vx = (node.vx || 0) + fx;
          node.vy = (node.vy || 0) + fy;
          other.vx = (other.vx || 0) - fx;
          other.vy = (other.vy || 0) - fy;
        }

        // Pull to center
        node.vx = (node.vx || 0) + (centerX - node.x) * centerForce;
        node.vy = (node.vy || 0) + (centerY - node.y) * centerForce;
      }

      // Spring forces along edges
      edges.forEach(edge => {
        const source = nodeArray.find(n => n.id === edge.from_node_id);
        const target = nodeArray.find(n => n.id === edge.to_node_id);
        if (!source || !target || !source.x || !source.y || !target.x || !target.y) return;

        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (dist - k) * c;

        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;

        source.vx = (source.vx || 0) + fx;
        source.vy = (source.vy || 0) + fy;
        target.vx = (target.vx || 0) - fx;
        target.vy = (target.vy || 0) - fy;
      });

      // Update positions
      nodeArray.forEach(node => {
        if (node.x === undefined || node.y === undefined) return;
        node.vx = (node.vx || 0) * damping;
        node.vy = (node.vy || 0) * damping;
        node.x += node.vx;
        node.y += node.vy;

        // Keep within bounds
        const padding = 30;
        node.x = Math.max(padding, Math.min(width - padding, node.x));
        node.y = Math.max(padding, Math.min(height - padding, node.y));
      });

      setSimulatedNodes([...nodeArray]);
      animationRef.current = requestAnimationFrame(simulate);
    };

    animationRef.current = requestAnimationFrame(simulate);

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [edges, width, height]);

  return simulatedNodes;
}

export default function KnowledgeGraph({ twinId, onNodeSelect }: KnowledgeGraphProps) {
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 });

  const supabase = getSupabaseClient();

  const getAuthToken = useCallback(async (): Promise<string | null> => {
    const { data: { session } } = await supabase.auth.getSession();
    return session?.access_token || null;
  }, [supabase]);

  // Update dimensions on resize (throttled)
  useEffect(() => {
    let resizeTimeout: NodeJS.Timeout;
    
    const updateDimensions = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setDimensions({
          width: Math.max(320, rect.width),
          height: Math.max(400, rect.height),
        });
      }
    };

    const throttledUpdate = () => {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(updateDimensions, 100);
    };

    updateDimensions();
    window.addEventListener('resize', throttledUpdate);
    return () => {
      window.removeEventListener('resize', throttledUpdate);
      clearTimeout(resizeTimeout);
    };
  }, []);

  // Fetch graph data
  useEffect(() => {
    const fetchGraph = async () => {
      if (!twinId) {
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);

      try {
        const token = await getAuthToken();
        if (!token) {
          setError('Not authenticated');
          setLoading(false);
          return;
        }

        const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.TWIN_GRAPH(twinId)}?limit=200`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });

        if (res.ok) {
          const json = await res.json();
          setData(json);
        } else {
          setError('Failed to load graph data');
        }
      } catch (e) {
        console.error("Graph fetch failed:", e);
        setError('Network error');
      } finally {
        setLoading(false);
      }
    };

    fetchGraph();
  }, [twinId, getAuthToken]);

  // Run force simulation
  const simulatedNodes = useForceSimulation(
    data?.nodes || [],
    data?.edges || [],
    dimensions.width,
    dimensions.height
  );

  // Create edge paths
  interface EdgePath {
    id: string;
    d: string;
    source: Node;
    target: Node;
  }
  
  const edgePaths = useMemo<EdgePath[]>(() => {
    return (data?.edges || []).map(edge => {
      const source = simulatedNodes.find(n => n.id === edge.from_node_id);
      const target = simulatedNodes.find(n => n.id === edge.to_node_id);
      if (!source || !target || source.x == null || source.y == null || target.x == null || target.y == null) {
        return null;
      }
      return {
        id: edge.id,
        d: `M ${source.x} ${source.y} L ${target.x} ${target.y}`,
        source,
        target,
      };
    }).filter((edge): edge is EdgePath => edge !== null);
  }, [data?.edges, simulatedNodes]);

  const handleNodeClick = (node: Node) => {
    setSelectedNode(node);
    onNodeSelect?.(node);
  };

  if (loading) {
    return (
      <div className="w-full h-[400px] flex items-center justify-center bg-slate-50 rounded-2xl border border-slate-200">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-slate-500 font-medium">Mapping sources...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full h-[400px] flex items-center justify-center bg-slate-50 rounded-2xl border border-slate-200">
        <div className="text-center">
          <p className="text-slate-500 font-medium">{error}</p>
          <button 
            onClick={() => window.location.reload()}
            className="mt-3 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div className="w-full h-[400px] flex items-center justify-center bg-slate-50 rounded-2xl border border-slate-200">
        <div className="text-center">
          <div className="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.384-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
            </svg>
          </div>
          <p className="text-slate-600 font-medium">No graph data yet</p>
          <p className="text-sm text-slate-400 mt-1">Add sources to see the graph</p>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="w-full h-[500px] relative bg-slate-900 rounded-2xl overflow-hidden">
      {/* Grid Background */}
      <div 
        className="absolute inset-0 opacity-20"
        style={{ 
          backgroundImage: 'radial-gradient(#2563EB 1px, transparent 1px)', 
          backgroundSize: '24px 24px' 
        }}
      />

      {/* SVG Graph */}
      <svg 
        width={dimensions.width} 
        height={dimensions.height}
        className="absolute inset-0 cursor-grab active:cursor-grabbing"
      >
        {/* Edges */}
        <g className="edges">
          {edgePaths.map(edge => edge && (
            <line
              key={edge.id}
              x1={edge.source.x}
              y1={edge.source.y}
              x2={edge.target.x}
              y2={edge.target.y}
              stroke="rgba(99, 102, 241, 0.3)"
              strokeWidth={1}
            />
          ))}
        </g>

        {/* Nodes */}
        <g className="nodes">
          {simulatedNodes.map(node => (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              className="cursor-pointer transition-transform hover:scale-110"
              onClick={() => handleNodeClick(node)}
              onMouseEnter={() => setHoveredNode(node.id)}
              onMouseLeave={() => setHoveredNode(null)}
            >
              {/* Node circle */}
              <circle
                r={hoveredNode === node.id ? 10 : 6}
                fill={getNodeColor(node.type)}
                stroke="white"
                strokeWidth={2}
                className="transition-all duration-200"
                filter="drop-shadow(0 0 4px rgba(0,0,0,0.3))"
              />
              
              {/* Label on hover */}
              {(hoveredNode === node.id || selectedNode?.id === node.id) && (
                <g transform="translate(12, 0)">
                  <rect
                    x={0}
                    y={-12}
                    width={Math.min(150, Math.max(50, (node.name?.length || 10) * 7)) + 16}
                    height={24}
                    rx={6}
                    fill="rgba(0, 0, 0, 0.8)"
                  />
                  <text
                    x={8}
                    y={4}
                    fill="white"
                    fontSize={11}
                    fontWeight={600}
                  >
                    {(node.name || 'Unknown').slice(0, 20)}{(node.name?.length || 0) > 20 ? '...' : ''}
                  </text>
                </g>
              )}
            </g>
          ))}
        </g>
      </svg>

      {/* Stats overlay */}
      <div className="absolute top-4 left-4 bg-black/50 backdrop-blur-sm rounded-xl px-4 py-3 text-white">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
          <span className="text-sm font-semibold">Live Graph</span>
        </div>
        <div className="mt-2 text-xs text-slate-300 space-y-1">
          <p>{data.stats.node_count} nodes</p>
          <p>{data.stats.edge_count} connections</p>
        </div>
      </div>

      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-black/50 backdrop-blur-sm rounded-xl px-4 py-3">
        <p className="text-xs font-semibold text-white mb-2">Node Types</p>
        <div className="space-y-1.5">
          {Object.entries(NODE_COLORS).filter(([k]) => k !== 'default').map(([type, color]) => (
            <div key={type} className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
              <span className="text-xs text-slate-300 capitalize">{type}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Selected node details */}
      {selectedNode && (
        <div className="absolute top-4 right-4 bg-white rounded-xl p-4 shadow-lg max-w-xs animate-in slide-in-from-right-2">
          <div className="flex items-start justify-between">
            <div>
              <span 
                className="inline-block w-3 h-3 rounded-full mb-2"
                style={{ backgroundColor: getNodeColor(selectedNode.type) }}
              />
              <h4 className="font-semibold text-slate-900 text-sm">{selectedNode.name}</h4>
              <p className="text-xs text-slate-500 mt-1 capitalize">{selectedNode.type}</p>
            </div>
            <button 
              onClick={() => setSelectedNode(null)}
              className="text-slate-400 hover:text-slate-600"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          {selectedNode.description && (
            <p className="mt-3 text-xs text-slate-600 line-clamp-3">{selectedNode.description}</p>
          )}
        </div>
      )}
    </div>
  );
}
