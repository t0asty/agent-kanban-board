// API Configuration
export const API_BASE_URL = 'http://localhost:8000'

// API Response Types
export interface ApiResponse<T> {
  success: boolean
  message: string
  data: T
}

export interface Card {
  id: string
  title: string
  description: string
  status: "research" | "in-progress" | "done" | "blocked" | "planned"
  order: number
  createdAt: string
  updatedAt: string
  tags: string[]
  completedAt: string | null
  agentStatus?: "idle" | "running" | "error" | null
  lastAgentRunAt?: string | null
  lastAgentSummary?: string | null
}

export interface CreateCardRequest {
  cards: Card[]
}

export interface UpdateCardRequest {
  title?: string
  description?: string
  status?: Card['status']
  order?: number
  tags?: string[]
  completedAt?: string | null
  agentStatus?: Card['agentStatus']
  lastAgentRunAt?: string | null
  lastAgentSummary?: string | null
}

export interface CardAgentRunPayload {
  run_id: string
  card_id: string
}

export interface CardAgentStatusPayload {
  status: 'idle' | 'running' | 'completed' | 'failed'
  run_id: string | null
  card_id: string
  step_count: number
  error: string | null
  summary: string | null
  started_at: string | null
  finished_at: string | null
}

export interface WorkspaceInfo {
  path: string | null
  configured: boolean
}

// API Client
class ApiClient {
  private baseURL: string

  constructor(baseURL: string) {
    this.baseURL = baseURL
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<ApiResponse<T>> {
    const url = `${this.baseURL}${endpoint}`
    
    const config: RequestInit = {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    }

    try {
      const response = await fetch(url, config)
      const json = await response.json().catch(() => ({}))

      if (!response.ok) {
        const msg =
          typeof json?.message === 'string'
            ? json.message
            : `HTTP error! status: ${response.status}`
        throw new Error(msg)
      }

      return json as ApiResponse<T>
    } catch (error) {
      console.error('API request failed:', error)
      throw error
    }
  }

  // Cards API
  async getCards(): Promise<ApiResponse<Card[]>> {
    return this.request<Card[]>('/api/cards')
  }

  async getCard(id: string): Promise<ApiResponse<Card>> {
    return this.request<Card>(`/api/cards/${id}`)
  }

  async createCards(cards: CreateCardRequest): Promise<ApiResponse<null>> {
    return this.request<null>('/api/cards', {
      method: 'POST',
      body: JSON.stringify(cards),
    })
  }

  async generateCardsWithAgent(prompt: string): Promise<ApiResponse<null>> {
    return this.request<null>('/api/generate-cards', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    })
  }

  async getWorkspace(): Promise<ApiResponse<WorkspaceInfo>> {
    return this.request<WorkspaceInfo>('/api/workspace')
  }

  /** Pass empty string to clear the workspace on the server. */
  async setWorkspace(path: string): Promise<ApiResponse<WorkspaceInfo>> {
    return this.request<WorkspaceInfo>('/api/workspace', {
      method: 'POST',
      body: JSON.stringify({ path: path.trim() === '' ? null : path }),
    })
  }

  async updateCard(id: string, updates: UpdateCardRequest): Promise<ApiResponse<Card>> {
    return this.request<Card>(`/api/cards/${id}`, {
      method: 'PUT',
      body: JSON.stringify(updates),
    })
  }

  async deleteCard(id: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/api/cards/${id}`, {
      method: 'DELETE',
    })
  }

  async deleteAllCards(): Promise<{ message: string }> {
    return this.request<{ message: string }>('/api/cards', {
      method: 'DELETE',
    })
  }

  async runCardAgent(
    cardId: string,
    opts?: { goal?: string; max_steps?: number; max_wall_seconds?: number }
  ): Promise<ApiResponse<CardAgentRunPayload>> {
    const url = `${this.baseURL}/api/cards/${encodeURIComponent(cardId)}/agent/run`
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        goal: opts?.goal ?? null,
        max_steps: opts?.max_steps ?? 16,
        max_wall_seconds: opts?.max_wall_seconds ?? 300,
      }),
    })
    const json = await response.json().catch(() => ({}))
    if (!response.ok) {
      const msg =
        typeof json?.message === 'string'
          ? json.message
          : `HTTP error! status: ${response.status}`
      throw new Error(msg)
    }
    return json as ApiResponse<CardAgentRunPayload>
  }

  async getCardAgentStatus(
    cardId: string
  ): Promise<{ success: boolean; message: string; data: CardAgentStatusPayload }> {
    const url = `${this.baseURL}/api/cards/${encodeURIComponent(cardId)}/agent/status`
    const response = await fetch(url)
    const json = await response.json().catch(() => ({}))
    if (!response.ok) {
      const msg =
        typeof json?.message === 'string'
          ? json.message
          : `HTTP error! status: ${response.status}`
      throw new Error(msg)
    }
    return json as { success: boolean; message: string; data: CardAgentStatusPayload }
  }

  // Health check
  async healthCheck(): Promise<{ message: string }> {
    return this.request<{ message: string }>('/')
  }
}

export const apiClient = new ApiClient(API_BASE_URL)
