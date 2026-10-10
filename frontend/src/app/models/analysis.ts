export type PedagogicalLevel = 'debutant' | 'intermediaire' | 'avance';

export interface AnalyzePositionRequest {
  fen: string;
  pgn: string;
  moves: string[];
  level: PedagogicalLevel;
  question?: string | null;
  rating_min?: number;
  rating_max?: number;
  session_id?: string | null;
}

export interface Opening {
  eco: string;
  name: string;
  matched: boolean;
  source: string;
}

export interface RecommendedMove {
  uci: string;
  san: string;
  description: string;
  source: string;
  games: number | null;
  white: number | null;
  draws: number | null;
  black: number | null;
  average_rating: number | null;
  move_share: number | null;
  relevant: boolean;
  badges: string[];
}

export interface LichessStats {
  source: string;
  games: number;
  white: number;
  draws: number;
  black: number;
}

export interface RagContext {
  text: string;
  source: string;
  url: string | null;
  chunk_id?: string | null;
  license_or_terms?: string | null;
  page_id?: string | null;
  canonical_title?: string | null;
  section_title?: string | null;
  relation_to_position?: string | null;
  entry_move?: string | null;
  opening_name?: string | null;
  eco_code?: string | null;
}

export interface Video {
  title: string;
  url: string;
  source: string;
  channel_title?: string | null;
  thumbnail_url?: string | null;
  published_at?: string | null;
  description?: string | null;
  duration_seconds?: number | null;
  view_count?: number | null;
}

export type FamilyStatus = 'pending' | 'running' | 'generated' | 'fallback' | 'failed' | 'skipped';
export type CoachStatus = FamilyStatus;

export interface AnalyzePositionResponse {
  opening: Opening;
  recommended_moves: RecommendedMove[];
  masters_moves: RecommendedMove[];
  masters_stats: LichessStats;
  lichess_stats: LichessStats | Record<string, never>;
  source_confidence: Record<string, unknown>;
  rag_context: RagContext[];
  coach_explanation: string;
  coach_status: CoachStatus;
  analysis_key: string | null;
  run_id: string | null;
  explorer_status: FamilyStatus;
  stockfish_status: FamilyStatus;
  rag_status: FamilyStatus;
  stockfish: Record<string, unknown> | null;
  videos: Video[];
  fallbacks_used: string[];
  session_id: string | null;
  cache: Record<string, string>;
}

export interface CoachExplanationRequest {
  run_id: string;
  level: PedagogicalLevel;
}

export interface CoachExplanationResponse {
  explanation: string;
  coach_status: CoachStatus;
  fallbacks_used: string[];
}

export interface StockfishRunResponse {
  stockfish: Record<string, unknown> | null;
  stockfish_status: FamilyStatus;
  fallbacks_used: string[];
}

export interface RagContextResponse {
  rag_context: RagContext[];
  rag_status: FamilyStatus;
  fallbacks_used: string[];
}

export interface CoachStreamDone {
  explanation: string;
  coach_status: CoachStatus;
  fallbacks_used: string[];
}
