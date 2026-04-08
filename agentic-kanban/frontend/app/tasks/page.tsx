"use client"

import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Sidebar } from "@/components/sidebar"
import { LoadingColumn, LoadingSpinner } from "@/components/ui/loading-spinner"
import { useCards, useOptimisticUpdateCard } from "@/hooks/use-cards"
import { useWorkspace } from "@/hooks/use-workspace"
import { useInitializeData } from "@/hooks/use-initialize-data"
import { useDeleteAllCards } from "@/hooks/use-delete-all-cards"
import type { Card as TaskCard } from "@/lib/api"
import { toast, Toaster } from "sonner"
import { ApiStatus } from "@/components/api-status"
import { Button } from "@/components/ui/button"
import { Plus, Trash2, Home, Eye } from "lucide-react"
import { TaskDetailDialog } from "@/components/task-detail-dialog"
import { useState } from "react"
import { useRouter } from "next/navigation"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"

const statusColumns = {
  research: { title: "Research", color: "bg-yellow-100 border-yellow-300 dark:bg-yellow-900/20" },
  planned: { title: "Planned", color: "bg-blue-100 border-blue-300 dark:bg-blue-900/20" },
  "in-progress": { title: "In Progress", color: "bg-orange-100 border-orange-300 dark:bg-orange-900/20" },
  blocked: { title: "Blocked", color: "bg-red-100 border-red-300 dark:bg-red-900/20" },
  done: { title: "Done", color: "bg-green-100 border-green-300 dark:bg-green-900/20" },
}

export default function TaskManagement() {
  const { data: tasks = [], isLoading, error } = useCards()
  const { data: workspaceInfo } = useWorkspace()
  const updateCardMutation = useOptimisticUpdateCard()
  const initializeDataMutation = useInitializeData()
  const deleteAllCardsMutation = useDeleteAllCards()
  const router = useRouter()
  
  // State for task detail dialog
  const [selectedTask, setSelectedTask] = useState<TaskCard | null>(null)
  const [isDetailDialogOpen, setIsDetailDialogOpen] = useState(false)

  const handleDragEnd = (result: any) => {
    if (!result.destination) return

    const { source, destination, draggableId } = result

    if (source.droppableId === destination.droppableId) return

    const newStatus = destination.droppableId as TaskCard["status"]
    const updates = {
      status: newStatus,
      completedAt: newStatus === 'done' ? new Date().toISOString() : undefined,
    }

    updateCardMutation.mutate(
      { id: draggableId, updates },
      {
        onSuccess: () => {
          toast.success(`Task moved to ${statusColumns[newStatus].title}`)
        },
        onError: () => {
          toast.error('Failed to update task status')
        },
      }
    )
  }

  const getTasksByStatus = (status: TaskCard["status"]) => tasks.filter((task) => task.status === status)

  const handleTaskClick = (task: TaskCard) => {
    setSelectedTask(task)
    setIsDetailDialogOpen(true)
  }

  const handleGoHome = () => {
    router.push('/')
  }

  // Handle empty state
  if (!isLoading && !error && tasks.length === 0) {
    return (
      <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
        <Sidebar />
        <main className="flex-1 overflow-hidden">
          <div className="h-full flex flex-col">
            <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Task Management</h1>
                  <p className="text-gray-600 dark:text-gray-300 mt-2">
                    Organize and track your tasks with our intelligent Kanban board
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleGoHome}
                    className="gap-2"
                  >
                    <Home className="w-4 h-4" />
                    Back to Home
                  </Button>
                  <ApiStatus />
                </div>
              </div>
            </header>
            <div className="flex-1 flex items-center justify-center p-6">
              <div className="text-center">
                <div className="text-gray-500 mb-6">
                  <h2 className="text-xl font-semibold mb-2">No tasks found</h2>
                  <p className="text-gray-600 dark:text-gray-400">
                    Get started by adding some sample tasks to your Kanban board
                  </p>
                </div>
                <Button
                  onClick={() => {
                    initializeDataMutation.mutate(undefined, {
                      onSuccess: () => {
                        toast.success('Sample tasks added successfully!')
                      },
                      onError: () => {
                        toast.error('Failed to add sample tasks')
                      },
                    })
                  }}
                  disabled={initializeDataMutation.isPending}
                  className="gap-2"
                >
                  {initializeDataMutation.isPending ? (
                    <LoadingSpinner size="sm" />
                  ) : (
                    <Plus className="w-4 h-4" />
                  )}
                  {initializeDataMutation.isPending ? 'Adding tasks...' : 'Add Sample Tasks'}
                </Button>
              </div>
            </div>
          </div>
        </main>
        <Toaster position="top-right" />
      </div>
    )
  }

  // Handle loading state
  if (isLoading) {
    return (
      <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
        <Sidebar />
        <main className="flex-1 overflow-hidden">
          <div className="h-full flex flex-col">
            <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Task Management</h1>
                  <p className="text-gray-600 dark:text-gray-300 mt-2">
                    Organize and track your tasks with our intelligent Kanban board
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleGoHome}
                    className="gap-2"
                  >
                    <Home className="w-4 h-4" />
                    Back to Home
                  </Button>
                  <ApiStatus />
                </div>
              </div>
            </header>
            <div className="flex-1 overflow-auto p-6">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-6 h-full">
                {Object.entries(statusColumns).map(([status, config]) => (
                  <LoadingColumn key={status} />
                ))}
              </div>
            </div>
          </div>
        </main>
      </div>
    )
  }

  // Handle error state
  if (error) {
    return (
      <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
        <Sidebar />
        <main className="flex-1 overflow-hidden">
          <div className="h-full flex flex-col">
            <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Task Management</h1>
                  <p className="text-gray-600 dark:text-gray-300 mt-2">
                    Organize and track your tasks with our intelligent Kanban board
                  </p>
                </div>
                <div className="flex items-center gap-4">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleGoHome}
                    className="gap-2"
                  >
                    <Home className="w-4 h-4" />
                    Back to Home
                  </Button>
                  <ApiStatus />
                </div>
              </div>
            </header>
            <div className="flex-1 flex items-center justify-center p-6">
              <div className="text-center">
                <div className="text-red-500 mb-4">
                  <LoadingSpinner size="lg" className="mx-auto mb-4" />
                  <h2 className="text-xl font-semibold">Failed to load tasks</h2>
                  <p className="text-gray-600 dark:text-gray-400 mt-2">
                    {error instanceof Error ? error.message : 'An unexpected error occurred'}
                  </p>
                </div>
                <button
                  onClick={() => window.location.reload()}
                  className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
                >
                  Try Again
                </button>
              </div>
            </div>
          </div>
        </main>
      </div>
    )
  }

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
      <Sidebar />

      <main className="flex-1 overflow-hidden">
        <div className="h-full flex flex-col">
          <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 p-6">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Task Management</h1>
                <p className="text-gray-600 dark:text-gray-300 mt-2">
                  Organize and track your tasks with our intelligent Kanban board
                </p>
                {workspaceInfo?.configured && workspaceInfo.path ? (
                  <p
                    className="text-xs text-gray-500 dark:text-gray-400 mt-2 font-mono truncate max-w-2xl"
                    title={workspaceInfo.path}
                  >
                    Agent workspace: {workspaceInfo.path}
                  </p>
                ) : (
                  <p className="text-xs text-amber-700 dark:text-amber-300 mt-2">
                    Card agents write files only when a workspace path is set on Home.
                  </p>
                )}
                {updateCardMutation.isPending && (
                  <div className="flex items-center gap-2 mt-2 text-sm text-blue-600 dark:text-blue-400">
                    <LoadingSpinner size="sm" />
                    <span>Updating task...</span>
                  </div>
                )}
              </div>
              <div className="flex items-center gap-4">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleGoHome}
                  className="gap-2"
                >
                  <Home className="w-4 h-4" />
                  Back to Home
                </Button>
                {tasks.length > 0 && (
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button
                        variant="destructive"
                        size="sm"
                        className="gap-2"
                        disabled={deleteAllCardsMutation.isPending}
                      >
                        {deleteAllCardsMutation.isPending ? (
                          <LoadingSpinner size="sm" />
                        ) : (
                          <Trash2 className="w-4 h-4" />
                        )}
                        Delete All Tasks
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Are you absolutely sure?</AlertDialogTitle>
                        <AlertDialogDescription>
                          This action cannot be undone. This will permanently delete all {tasks.length} tasks from your kanban board.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => {
                            deleteAllCardsMutation.mutate(undefined, {
                              onSuccess: (response) => {
                                toast.success(response.message || 'All tasks deleted successfully!')
                              },
                              onError: (error) => {
                                toast.error('Failed to delete tasks: ' + (error instanceof Error ? error.message : 'Unknown error'))
                              },
                            })
                          }}
                          className="bg-red-600 hover:bg-red-700"
                        >
                          Delete All Tasks
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                )}
                <ApiStatus />
              </div>
            </div>
          </header>

          <div className="flex-1 overflow-auto p-6">
            <DragDropContext onDragEnd={handleDragEnd}>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-6 h-full">
                {Object.entries(statusColumns).map(([status, config]) => (
                  <div key={status} className="flex flex-col">
                    <div className={`rounded-lg border-2 border-dashed p-4 mb-4 ${config.color}`}>
                      <h2 className="font-semibold text-lg text-center">{config.title}</h2>
                      <p className="text-sm text-center text-gray-600 dark:text-gray-400 mt-1">
                        {getTasksByStatus(status as TaskCard["status"]).length} tasks
                      </p>
                    </div>

                    <Droppable droppableId={status}>
                      {(provided, snapshot) => (
                        <div
                          ref={provided.innerRef}
                          {...provided.droppableProps}
                          className={`flex-1 space-y-3 p-2 rounded-lg transition-colors ${
                            snapshot.isDraggingOver ? "bg-gray-100 dark:bg-gray-800" : ""
                          }`}
                        >
                          {getTasksByStatus(status as TaskCard["status"]).map((task, index) => (
                            <Draggable key={task.id} draggableId={task.id} index={index}>
                              {(provided, snapshot) => (
                                <Card
                                  ref={provided.innerRef}
                                  {...provided.draggableProps}
                                  className={`cursor-pointer hover:shadow-md transition-shadow relative ${
                                    snapshot.isDragging ? "shadow-lg rotate-2" : ""
                                  }`}
                                  onClick={() => handleTaskClick(task)}
                                >
                                  <div 
                                    {...provided.dragHandleProps} 
                                    className="absolute top-2 right-2 p-1 cursor-grab active:cursor-grabbing opacity-30 hover:opacity-60 transition-opacity z-10"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    <div className="w-4 h-4 grid grid-cols-2 gap-0.5">
                                      <div className="w-1 h-1 bg-gray-400 rounded-full"></div>
                                      <div className="w-1 h-1 bg-gray-400 rounded-full"></div>
                                      <div className="w-1 h-1 bg-gray-400 rounded-full"></div>
                                      <div className="w-1 h-1 bg-gray-400 rounded-full"></div>
                                    </div>
                                  </div>
                                  <CardHeader className="pb-3 pr-8">
                                    <CardTitle className="text-sm font-medium">{task.title}</CardTitle>
                                  </CardHeader>
                                  <CardContent className="pt-0">
                                    <CardDescription 
                                      className="text-xs mb-3 overflow-hidden"
                                      style={{
                                        display: '-webkit-box',
                                        WebkitLineClamp: 3,
                                        WebkitBoxOrient: 'vertical',
                                      }}
                                    >
                                      {task.description}
                                    </CardDescription>
                                    {task.tags && task.tags.length > 0 && (
                                      <div className="flex flex-wrap gap-1">
                                        {task.tags.map((tag) => (
                                          <Badge key={tag} variant="secondary" className="text-xs">
                                            {tag}
                                          </Badge>
                                        ))}
                                      </div>
                                    )}
                                  </CardContent>
                                </Card>
                              )}
                            </Draggable>
                          ))}
                          {provided.placeholder}
                        </div>
                      )}
                    </Droppable>
                  </div>
                ))}
              </div>
            </DragDropContext>
          </div>
        </div>
      </main>
      <Toaster position="top-right" />
      <TaskDetailDialog 
        task={selectedTask} 
        open={isDetailDialogOpen} 
        onOpenChange={setIsDetailDialogOpen} 
      />
    </div>
  )
}
