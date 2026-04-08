import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api'

const WORKSPACE_STORAGE_KEY = 'kanban-agent-workspace-path'

export const workspaceKeys = {
  all: ['workspace'] as const,
  current: () => [...workspaceKeys.all, 'current'] as const,
}

export function useWorkspace() {
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: workspaceKeys.current(),
    queryFn: async () => {
      const res = await apiClient.getWorkspace()
      if (!res.success || !res.data) {
        throw new Error(res.message || 'Failed to load workspace')
      }
      return res.data
    },
    staleTime: 30_000,
  })

  const setMutation = useMutation({
    mutationFn: async (path: string) => {
      const res = await apiClient.setWorkspace(path)
      if (!res.success || !res.data) {
        throw new Error(res.message || 'Failed to update workspace')
      }
      return res.data
    },
    onSuccess: (data) => {
      if (typeof window !== 'undefined') {
        if (data.path) {
          localStorage.setItem(WORKSPACE_STORAGE_KEY, data.path)
        } else {
          localStorage.removeItem(WORKSPACE_STORAGE_KEY)
        }
      }
      queryClient.setQueryData(workspaceKeys.current(), data)
    },
  })

  return { ...query, setWorkspace: setMutation.mutateAsync, setWorkspaceStatus: setMutation }
}

export function getStoredWorkspacePath(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(WORKSPACE_STORAGE_KEY)
}

export { WORKSPACE_STORAGE_KEY }
