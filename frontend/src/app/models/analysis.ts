export type PedagogicalLevel = 'debutant' | 'intermediaire' | 'avance';

export interface AnalyzePositionRequest {
  fen: string;
  pgn: string;
  moves: string[];
  level: PedagogicalLevel;
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
}

export interface Video {
  title: string;
  url: string;
  source: string;
}

export interface AnalyzePositionResponse {
  opening: Opening;
  recommended_moves: RecommendedMove[];
  masters_moves: RecommendedMove[];
  masters_stats: LichessStats;
  lichess_stats: LichessStats | Record<string, never>;
  source_confidence: Record<string, unknown>;
  rag_context: RagContext[];
  coach_explanation: string;
  stockfish: Record<string, unknown> | null;
  videos: Video[];
  fallbacks_used: string[];
  session_id: string | null;
  cache: Record<string, string>;
}
