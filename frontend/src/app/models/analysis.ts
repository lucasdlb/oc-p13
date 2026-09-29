export type PedagogicalLevel = 'debutant' | 'intermediaire' | 'avance';

export interface AnalyzePositionRequest {
  fen: string;
  pgn: string;
  moves: string[];
  level: PedagogicalLevel;
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
  lichess_stats: LichessStats | Record<string, never>;
  rag_context: RagContext[];
  coach_explanation: string;
  stockfish: Record<string, unknown> | null;
  videos: Video[];
  fallbacks_used: string[];
}
