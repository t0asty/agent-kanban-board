"use client"

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card as TaskCard } from "@/lib/api"
import { useCardAgentStatus, useRunCardAgent, cardKeys } from "@/hooks/use-cards"
import { useWorkspace } from "@/hooks/use-workspace"
import { useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { Calendar, Clock, Tag, Bot, Loader2, FolderOpen } from "lucide-react"
import { format } from "date-fns"
import { useEffect } from "react"
import { toast } from "sonner"

interface TaskDetailDialogProps {
  task: TaskCard | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

const statusConfig = {
  research: { label: "Research", color: "bg-yellow-100 text-yellow-800 border-yellow-300" },
  planned: { label: "Planned", color: "bg-blue-100 text-blue-800 border-blue-300" },
  "in-progress": { label: "In Progress", color: "bg-orange-100 text-orange-800 border-orange-300" },
  blocked: { label: "Blocked", color: "bg-red-100 text-red-800 border-red-300" },
  done: { label: "Done", color: "bg-green-100 text-green-800 border-green-300" },
}

const agentBoardStatusConfig: Record<
  NonNullable<TaskCard["agentStatus"]>,
  { label: string; color: string }
> = {
  idle: { label: "Agent idle", color: "bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800/40" },
  running: { label: "Agent running", color: "bg-violet-100 text-violet-800 border-violet-300 dark:bg-violet-900/30" },
  error: { label: "Agent error", color: "bg-red-100 text-red-800 border-red-300 dark:bg-red-900/30" },
}

export function TaskDetailDialog({ task, open, onOpenChange }: TaskDetailDialogProps) {
  const queryClient = useQueryClient()
  const runAgent = useRunCardAgent()
  const { data: workspaceInfo } = useWorkspace()
  const { data: agentRun, isFetching: agentStatusFetching } = useCardAgentStatus(
    task?.id,
    open
  )

  useEffect(() => {
    const s = agentRun?.status
    if (s === "completed" || s === "failed") {
      queryClient.invalidateQueries({ queryKey: cardKeys.lists() })
    }
  }, [agentRun?.status, queryClient])

  if (!task) return null

  const status = statusConfig[task.status]
  const boardAgent = task.agentStatus ?? "idle"
  const boardAgentCfg =
    boardAgent in agentBoardStatusConfig
      ? agentBoardStatusConfig[boardAgent as NonNullable<TaskCard["agentStatus"]>]
      : agentBoardStatusConfig.idle
  const runInFlight = agentRun?.status === "running"
  const runBusy = runInFlight || runAgent.isPending
  
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-xl font-semibold pr-6">
            {task.title}
          </DialogTitle>
        </DialogHeader>
        
        <div className="space-y-6">
          {/* Status and Order */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Badge className={`${status.color} border`}>
                {status.label}
              </Badge>
            </div>
            <div className="text-sm text-gray-500">
              Order: {task.order}
            </div>
          </div>

          {/* Description */}
          <div>
            <h3 className="font-medium text-gray-900 dark:text-gray-100 mb-2">Description</h3>
            <p className="text-gray-700 dark:text-gray-300 leading-relaxed">
              {task.description || "No description provided"}
            </p>
          </div>

          {/* Tags */}
          {task.tags && task.tags.length > 0 && (
            <div>
              <h3 className="font-medium text-gray-900 dark:text-gray-100 mb-2 flex items-center gap-2">
                <Tag className="w-4 h-4" />
                Tags
              </h3>
              <div className="flex flex-wrap gap-2">
                {task.tags.map((tag) => (
                  <Badge key={tag} variant="outline" className="text-xs">
                    {tag}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Per-card agent */}
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 space-y-3 bg-gray-50/80 dark:bg-gray-900/40">
            <h3 className="font-medium text-gray-900 dark:text-gray-100 flex items-center gap-2">
              <Bot className="w-4 h-4" />
              Card agent
            </h3>
            {workspaceInfo?.configured && workspaceInfo.path ? (
              <p className="text-xs text-gray-600 dark:text-gray-400 flex items-start gap-2">
                <FolderOpen className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span>
                  Workspace files (server path):{" "}
                  <span className="font-mono break-all text-gray-800 dark:text-gray-200">
                    {workspaceInfo.path}
                  </span>
                  . Look for{" "}
                  <span className="font-mono">kanban-agent-output/{task.id}/</span> after a run.
                </span>
              </p>
            ) : (
              <p className="text-xs rounded-md border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-950/30 text-amber-900 dark:text-amber-100 px-3 py-2">
                No workspace folder is set on the backend — the agent can only edit this card, not
                create files in your project. Open{" "}
                <Link href="/" className="underline font-medium">
                  Home
                </Link>{" "}
                and set <strong>Agent workspace</strong> to an absolute path (your repo root), then
                run the agent again.
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge className={`${boardAgentCfg.color} border`}>{boardAgentCfg.label}</Badge>
              {agentRun && agentRun.status !== "idle" && (
                <span className="text-gray-600 dark:text-gray-400">
                  Run: <span className="font-mono text-xs">{agentRun.status}</span>
                  {agentRun.step_count > 0 ? ` · ${agentRun.step_count} tool calls` : null}
                  {agentStatusFetching && runInFlight ? (
                    <Loader2 className="inline w-3 h-3 ml-1 animate-spin align-middle" />
                  ) : null}
                </span>
              )}
            </div>
            {agentRun?.error && (
              <p className="text-sm text-red-600 dark:text-red-400">{agentRun.error}</p>
            )}
            {(task.lastAgentSummary || agentRun?.summary) && (
              <div>
                <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                  Last summary
                </p>
                <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                  {runInFlight && agentRun?.summary
                    ? agentRun.summary
                    : task.lastAgentSummary || agentRun?.summary}
                </p>
              </div>
            )}
            {task.lastAgentRunAt && (
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Last agent run:{" "}
                {format(new Date(task.lastAgentRunAt), "MMM d, yyyy 'at' h:mm a")}
              </p>
            )}
            <Button
              type="button"
              size="sm"
              disabled={runBusy}
              className="gap-2"
              onClick={() => {
                runAgent.mutate(
                  { cardId: task.id },
                  {
                    onSuccess: () => toast.success("Agent run started"),
                    onError: (e) =>
                      toast.error(e instanceof Error ? e.message : "Failed to start agent"),
                  }
                )
              }}
            >
              {runBusy ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Bot className="w-4 h-4" />
              )}
              {runInFlight ? "Agent working…" : "Run agent on this card"}
            </Button>
          </div>

          {/* Timestamps */}
          <div>
            <h3 className="font-medium text-gray-900 dark:text-gray-100 mb-3 flex items-center gap-2">
              <Clock className="w-4 h-4" />
              Timeline
            </h3>
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                <Calendar className="w-3 h-3" />
                <span className="font-medium">Created:</span>
                {format(new Date(task.createdAt), "MMM d, yyyy 'at' h:mm a")}
              </div>
              <div className="flex items-center gap-2 text-gray-600 dark:text-gray-400">
                <Calendar className="w-3 h-3" />
                <span className="font-medium">Updated:</span>
                {format(new Date(task.updatedAt), "MMM d, yyyy 'at' h:mm a")}
              </div>
              {task.completedAt && (
                <div className="flex items-center gap-2 text-green-600 dark:text-green-400">
                  <Calendar className="w-3 h-3" />
                  <span className="font-medium">Completed:</span>
                  {format(new Date(task.completedAt), "MMM d, yyyy 'at' h:mm a")}
                </div>
              )}
            </div>
          </div>

          {/* Task ID for debugging/reference */}
          <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
            <div className="text-xs text-gray-500 dark:text-gray-400">
              Task ID: {task.id}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}