import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient, type Card, type CreateCardRequest, type UpdateCardRequest } from '@/lib/api'

// Query Keys
export const cardKeys = {
  all: ['cards'] as const,
  lists: () => [...cardKeys.all, 'list'] as const,
  list: (filters: string) => [...cardKeys.lists(), { filters }] as const,
  details: () => [...cardKeys.all, 'detail'] as const,
  detail: (id: string) => [...cardKeys.details(), id] as const,
}

export const cardAgentKeys = {
  status: (cardId: string) => ['cardAgentStatus', cardId] as const,
}

// Get all cards
export function useCards() {
  return useQuery({
    queryKey: cardKeys.lists(),
    queryFn: async () => {
      const response = await apiClient.getCards()
      return response.data
    },
    staleTime: 1000 * 60 * 5, // 5 minutes
    gcTime: 1000 * 60 * 10, // 10 minutes
  })
}

// Get single card
export function useCard(id: string) {
  return useQuery({
    queryKey: cardKeys.detail(id),
    queryFn: async () => {
      const response = await apiClient.getCard(id)
      return response.data
    },
    enabled: !!id,
    staleTime: 1000 * 60 * 5, // 5 minutes
  })
}

// Create cards
export function useCreateCards() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: async (cards: CreateCardRequest) => {
      const response = await apiClient.createCards(cards)
      return response
    },
    onSuccess: () => {
      // Invalidate and refetch cards list
      queryClient.invalidateQueries({ queryKey: cardKeys.lists() })
    },
  })
}

// Update card
export function useUpdateCard() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: async ({ id, updates }: { id: string; updates: UpdateCardRequest }) => {
      const response = await apiClient.updateCard(id, updates)
      return response.data
    },
    onSuccess: (updatedCard) => {
      // Update the specific card in cache
      queryClient.setQueryData(cardKeys.detail(updatedCard.id), updatedCard)
      
      // Invalidate and refetch cards list
      queryClient.invalidateQueries({ queryKey: cardKeys.lists() })
    },
  })
}

// Delete card
export function useDeleteCard() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: async (id: string) => {
      const response = await apiClient.deleteCard(id)
      return response
    },
    onSuccess: (_, deletedId) => {
      // Remove the card from cache
      queryClient.removeQueries({ queryKey: cardKeys.detail(deletedId) })
      
      // Invalidate and refetch cards list
      queryClient.invalidateQueries({ queryKey: cardKeys.lists() })
    },
  })
}

// Optimistic update for drag and drop
export function useOptimisticUpdateCard() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: async ({ id, updates }: { id: string; updates: UpdateCardRequest }) => {
      const response = await apiClient.updateCard(id, updates)
      return response.data
    },
    onMutate: async ({ id, updates }) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: cardKeys.lists() })
      
      // Snapshot the previous value
      const previousCards = queryClient.getQueryData(cardKeys.lists())
      
      // Optimistically update to the new value
      queryClient.setQueryData(cardKeys.lists(), (old: Card[] | undefined) => {
        if (!old) return old
        return old.map(card => 
          card.id === id ? { ...card, ...updates, updatedAt: new Date().toISOString() } : card
        )
      })
      
      // Return a context object with the snapshotted value
      return { previousCards }
    },
    onError: (err, variables, context) => {
      // If the mutation fails, use the context returned from onMutate to roll back
      if (context?.previousCards) {
        queryClient.setQueryData(cardKeys.lists(), context.previousCards)
      }
    },
    onSettled: () => {
      // Always refetch after error or success
      queryClient.invalidateQueries({ queryKey: cardKeys.lists() })
    },
  })
}

export function useCardAgentStatus(cardId: string | undefined, open: boolean) {
  return useQuery({
    queryKey: cardAgentKeys.status(cardId ?? ''),
    queryFn: async () => {
      const res = await apiClient.getCardAgentStatus(cardId!)
      return res.data
    },
    enabled: !!cardId && open,
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? 2000 : false,
  })
}

export function useRunCardAgent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      cardId,
      opts,
    }: {
      cardId: string
      opts?: { goal?: string; max_steps?: number; max_wall_seconds?: number }
    }) => {
      return apiClient.runCardAgent(cardId, opts)
    },
    onSuccess: (_res, { cardId }) => {
      queryClient.invalidateQueries({ queryKey: cardKeys.lists() })
      queryClient.invalidateQueries({ queryKey: cardAgentKeys.status(cardId) })
    },
  })
}
