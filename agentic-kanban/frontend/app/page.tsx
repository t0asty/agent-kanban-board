"use client"

import type React from "react"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LoadingSpinner } from "@/components/ui/loading-spinner"
import { useGenerateCards } from "@/hooks/use-generate-cards"
import { getStoredWorkspacePath, useWorkspace } from "@/hooks/use-workspace"
import { FolderOpen, Send, Sparkles } from "lucide-react"
import { useToast } from "@/hooks/use-toast"

export default function TaskGenerator() {
  const router = useRouter()
  const generateCardsMutation = useGenerateCards()
  const {
    data: workspaceInfo,
    isLoading: workspaceLoading,
    setWorkspace,
    setWorkspaceStatus,
  } = useWorkspace()
  const { toast } = useToast()
  const [inputValue, setInputValue] = useState("")
  const [workspaceInput, setWorkspaceInput] = useState("")
  const [isCreatingTasks, setIsCreatingTasks] = useState(false)
  const restoredFromBrowserRef = useRef(false)

  useEffect(() => {
    if (workspaceInfo?.path) {
      setWorkspaceInput(workspaceInfo.path)
    }
  }, [workspaceInfo?.path])

  useEffect(() => {
    if (!workspaceLoading && workspaceInfo && !restoredFromBrowserRef.current) {
      restoredFromBrowserRef.current = true
      if (!workspaceInfo.configured) {
        const stored = getStoredWorkspacePath()
        if (stored) {
          setWorkspace(stored).catch(() => {
            /* invalid path; user can fix in UI */
          })
        }
      }
    }
  }, [workspaceLoading, workspaceInfo, setWorkspace])

  const handleGenerateTasks = async () => {
    if (!inputValue.trim()) return

    setIsCreatingTasks(true)

    // Generate tasks using Gemini API
    generateCardsMutation.mutate(inputValue, {
      onSuccess: () => {
        toast({
          title: "Tasks Generated!",
          description: "Your kanban board has been created with AI-generated tasks.",
        })
        // Redirect immediately to tasks page
        router.push('/tasks')
      },
      onError: (error) => {
        setIsCreatingTasks(false)
        toast({
          title: "Error generating tasks",
          description: error instanceof Error ? error.message : "Please try again",
          variant: "destructive",
        })
      }
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleGenerateTasks()
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800 flex items-center justify-center p-4">
      <div className="w-full max-w-2xl">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-3 mb-4">
            <div className="p-3 bg-blue-600 rounded-full">
              <Sparkles className="h-8 w-8 text-white" />
            </div>
          </div>
          <h1 className="text-4xl font-bold text-gray-900 dark:text-white mb-2">
            AI Task Generator
          </h1>
          <p className="text-lg text-gray-600 dark:text-gray-300">
            Describe your project and I'll create a Kanban board for you
          </p>
        </div>

        {/* Input Section */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl p-8">
          <div className="space-y-6">
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-3 bg-gray-50/80 dark:bg-gray-900/40">
              <div className="flex items-center gap-2 text-sm font-medium text-gray-800 dark:text-gray-200">
                <FolderOpen className="h-4 w-4 shrink-0" />
                Agent workspace (server path)
              </div>
              <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed">
                Enter the absolute folder on the machine where the backend runs. The model can list, read, and write
                files only under this directory when generating tasks.
              </p>
              <div className="space-y-2">
                <Label htmlFor="workspace-path" className="text-xs text-gray-600 dark:text-gray-400">
                  Folder path
                </Label>
                <div className="flex flex-col sm:flex-row gap-2">
                  <Input
                    id="workspace-path"
                    value={workspaceInput}
                    onChange={(e) => setWorkspaceInput(e.target.value)}
                    placeholder="/Users/you/projects/my-app"
                    className="font-mono text-sm flex-1"
                    disabled={setWorkspaceStatus.isPending || workspaceLoading}
                  />
                  <div className="flex gap-2 shrink-0">
                    <Button
                      type="button"
                      variant="secondary"
                      className="sm:w-auto w-full"
                      disabled={setWorkspaceStatus.isPending || workspaceLoading || !workspaceInput.trim()}
                      onClick={async () => {
                        try {
                          await setWorkspace(workspaceInput)
                          toast({
                            title: "Workspace updated",
                            description: "Agents can use this folder when generating tasks.",
                          })
                        } catch (e) {
                          toast({
                            title: "Could not set workspace",
                            description: e instanceof Error ? e.message : "Check the path exists on the server.",
                            variant: "destructive",
                          })
                        }
                      }}
                    >
                      {setWorkspaceStatus.isPending ? <LoadingSpinner size="sm" /> : "Save"}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="sm:w-auto w-full"
                      disabled={setWorkspaceStatus.isPending || workspaceLoading || !workspaceInfo?.configured}
                      onClick={async () => {
                        try {
                          await setWorkspace("")
                          setWorkspaceInput("")
                          toast({ title: "Workspace cleared" })
                        } catch (e) {
                          toast({
                            title: "Could not clear workspace",
                            description: e instanceof Error ? e.message : "Try again",
                            variant: "destructive",
                          })
                        }
                      }}
                    >
                      Clear
                    </Button>
                  </div>
                </div>
                {workspaceInfo?.configured && workspaceInfo.path && (
                  <p className="text-xs text-green-700 dark:text-green-400 font-mono break-all">
                    Active: {workspaceInfo.path}
                  </p>
                )}
              </div>
            </div>

            <div className="flex gap-3">
              <Input
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="e.g., Create tasks for a web app project, Organize my marketing campaign..."
                className="flex-1 text-lg"
                disabled={isCreatingTasks}
              />
              <Button 
                onClick={handleGenerateTasks} 
                disabled={isCreatingTasks || !inputValue.trim()}
                size="lg"
                className="px-6"
              >
                {isCreatingTasks ? (
                  <LoadingSpinner size="sm" />
                ) : (
                  <Send className="h-5 w-5" />
                )}
              </Button>
            </div>
            
            {isCreatingTasks && (
              <div className="flex items-center gap-3 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                <LoadingSpinner size="sm" />
                <div>
                  <p className="font-medium text-blue-900 dark:text-blue-100">
                    Creating your Kanban board...
                  </p>
                  <p className="text-sm text-blue-700 dark:text-blue-200">
                    Analyzing your request and generating tasks
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Examples */}
        <div className="mt-8 text-center">
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">Try these examples:</p>
          <div className="flex flex-wrap gap-2 justify-center">
            {[
              "Create tasks for a web app project",
              "Organize my marketing campaign", 
              "Plan a product launch",
              "Set up a development workflow"
            ].map((example) => (
              <button
                key={example}
                onClick={() => setInputValue(example)}
                className="px-3 py-1 text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-full hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
