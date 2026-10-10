import { Component, computed, input, output, signal } from '@angular/core';
import { PercentPipe } from '@angular/common';

import { AnalyzePositionResponse, RecommendedMove, Video } from '../models/analysis';
import { CoachMarkdownComponent } from '../coach-markdown/coach-markdown';
import { BoardMove } from '../models/game';

@Component({
  selector: 'app-analysis-panel',
  imports: [CoachMarkdownComponent, PercentPipe],
  templateUrl: './analysis-panel.html',
  styleUrl: './analysis-panel.css',
})
export class AnalysisPanelComponent {
  readonly analysis = input<AnalyzePositionResponse | null>(null);
  readonly fen = input('');
  readonly legalMoves = input<string[]>([]);
  readonly activeQuestion = input<string | null>(null);
  readonly ratingMin = input(0);
  readonly ratingMax = input(2500);
  readonly ratingBuckets = input<number[]>([]);
  readonly ratingMinChange = output<number>();
  readonly ratingMaxChange = output<number>();
  readonly movePreview = output<BoardMove | null>();
  readonly squarePreview = output<string | null>();
  readonly moveRequested = output<BoardMove>();
  readonly lineRequested = output<BoardMove[]>();
  readonly questionSubmit = output<string>();
  readonly explanationRequest = output<void>();
  readonly loading = input(false);
  readonly stockfishLoading = input(false);
  readonly ragLoading = input(false);
  readonly coachStreaming = input(false);
  readonly error = input<string | null>(null);
  readonly activeExplorer = signal<'lichess' | 'masters'>('lichess');
  readonly activePanel = signal<'stats' | 'sources' | 'videos'>('stats');

  submitQuestion(event: SubmitEvent, value: string): void {
    event.preventDefault();
    const question = value.trim();
    if (question) {
      this.questionSubmit.emit(question);
    }
  }

  readonly sortedRecommendedMoves = computed(() => {
    const moves = this.analysis()?.recommended_moves ?? [];
    const winningSide = this.sideToMove() === 'black' ? 'black' : 'white';

    return [...moves].sort((left, right) =>
      this.compareMovesByWinningChance(left, right, winningSide),
    );
  });

  readonly coachMoves = computed(() => {
    const result = this.analysis();
    if (!result) {
      return [];
    }

    return [...new Map(
      [...result.recommended_moves, ...result.masters_moves]
        .map((move) => [move.uci, move] as const),
    ).values()];
  });

  hasStats(): boolean {
    const stats = this.analysis()?.lichess_stats;
    return !!stats && 'games' in stats;
  }

  activeExplorerLabel(): string {
    return this.activeExplorer() === 'masters' ? 'Masters explorer' : 'Lichess explorer';
  }

  activeExplorerTotal(): number | null {
    const analysis = this.analysis();
    if (!analysis) {
      return null;
    }

    if (this.activeExplorer() === 'masters') {
      return analysis.masters_stats.games;
    }

    const stats = analysis.lichess_stats;
    return 'games' in stats ? stats.games : null;
  }

  formattedExplorerTotal(): string | null {
    const total = this.activeExplorerTotal();
    return total === null ? null : this.formatCompactNumber(total);
  }

  visibleBadges(move: RecommendedMove, source: 'lichess' | 'masters'): string[] {
    const hiddenSource = source === 'masters' ? 'Masters' : 'Lichess';
    return move.badges.filter((badge) => badge !== hiddenSource && !badge.startsWith('Elo '));
  }

  formattedGames(move: RecommendedMove): string {
    return move.games === null ? '-' : this.formatCompactNumber(move.games);
  }

  setRatingMin(value: string): void {
    this.ratingMinChange.emit(Number(value));
  }

  setRatingMax(value: string): void {
    this.ratingMaxChange.emit(Number(value));
  }

  averageRatingLabel(move: RecommendedMove): string | null {
    return move.average_rating === null ? null : `Elo ${move.average_rating}`;
  }

  showExplorerTab(tab: 'lichess' | 'masters'): void {
    this.activeExplorer.set(tab);
  }

  showPanel(panel: 'stats' | 'sources' | 'videos'): void {
    this.activePanel.set(panel);
  }

  panelLabel(panel: 'stats' | 'sources' | 'videos'): string {
    return panel === 'stats' ? 'Statistiques' : panel === 'sources' ? 'Sources' : 'Vidéos';
  }

  videoSourceLabel(video: Video): string {
    return video.source === 'youtube-data-api' ? 'YouTube' : 'Recherche YouTube';
  }

  videoDuration(video: Video): string | null {
    if (video.duration_seconds == null) {
      return null;
    }
    const minutes = Math.floor(video.duration_seconds / 60);
    const seconds = video.duration_seconds % 60;
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  }

  previewRecommendedMove(move: RecommendedMove): void {
    const boardMove = this.toBoardMove(move.uci);
    if (boardMove) {
      this.movePreview.emit(boardMove);
    }
  }

  clearMovePreview(): void {
    this.movePreview.emit(null);
  }

  requestMove(move: RecommendedMove): void {
    const boardMove = this.toBoardMove(move.uci);
    if (boardMove) {
      this.moveRequested.emit(boardMove);
    }
  }

  contextRelationLabel(context: AnalyzePositionResponse['rag_context'][number]): string {
    if (context.relation_to_position === 'child' && context.entry_move) {
      return `Suite apres ${context.entry_move}`;
    }

    if (context.relation_to_position === 'fallback') {
      return 'Contexte de secours';
    }

    return 'Position actuelle';
  }

  stockfishLabel(): string {
    const analysis = this.analysis();
    if (!analysis) {
      return 'Évaluation indisponible';
    }

    if (analysis.stockfish_status === 'pending' || analysis.stockfish_status === 'running') {
      return 'Évaluation en cours...';
    }

    if (analysis.stockfish_status === 'skipped') {
      return 'Pas d’appel moteur nécessaire pour cette position.';
    }

    const engineStatus = analysis.stockfish?.['status'];
    if (engineStatus === 'unavailable') {
      return `Indisponible (${analysis.stockfish?.['reason'] ?? 'raison inconnue'})`;
    }

    if (analysis.stockfish_status === 'failed') {
      return 'Échec de l’évaluation moteur.';
    }

    return 'Évaluation indisponible';
  }

  stockfishMoves(): string[] {
    const stockfish = this.analysis()?.stockfish;
    if (!stockfish || stockfish['status'] !== 'ok') {
      return [];
    }

    const candidates: unknown[] = [stockfish['best_move']];
    if (Array.isArray(stockfish['variations'])) {
      for (const variation of stockfish['variations']) {
        if (variation && typeof variation === 'object') {
          candidates.push((variation as Record<string, unknown>)['best_move']);
        }
      }
    }

    return [...new Set(candidates.filter((move): move is string => typeof move === 'string'))]
      .filter((move) => this.toBoardMove(move) !== null);
  }

  previewStockfishMove(uci: string): void {
    const boardMove = this.toBoardMove(uci);
    if (boardMove) {
      this.movePreview.emit(boardMove);
    }
  }

  requestStockfishMove(uci: string): void {
    const boardMove = this.toBoardMove(uci);
    if (boardMove) {
      this.moveRequested.emit(boardMove);
    }
  }

  stockfishDepth(): number | null {
    const depth = this.analysis()?.stockfish?.['depth'];
    return typeof depth === 'number' ? depth : null;
  }

  stockfishDetails(): string | null {
    const stockfish = this.analysis()?.stockfish;
    if (!stockfish || stockfish['status'] !== 'ok') {
      return null;
    }

    const score = stockfish['score'] as { type?: string; value?: number } | undefined;
    const scoreLabel = score?.type && score.value !== undefined
      ? `${score.type} ${score.value > 0 ? '+' : ''}${score.value}`
      : 'score indisponible';
    const bestMove = typeof stockfish['best_move'] === 'string'
      ? stockfish['best_move']
      : 'coup indisponible';
    return `Meilleur coup ${bestMove} · ${scoreLabel}`;
  }

  private formatCompactNumber(value: number): string {
    if (value >= 1_000_000_000) {
      return `${this.trimDecimal(value / 1_000_000_000)} Md`;
    }

    if (value >= 1_000_000) {
      return `${this.trimDecimal(value / 1_000_000)} M`;
    }

    if (value >= 1_000) {
      return `${this.trimDecimal(value / 1_000)} k`;
    }

    return new Intl.NumberFormat('fr-FR').format(value);
  }

  private trimDecimal(value: number): string {
    return value.toLocaleString('fr-FR', {
      maximumFractionDigits: value >= 10 ? 0 : 1,
    });
  }

  private sideToMove(): 'white' | 'black' {
    return this.fen().split(' ')[1] === 'b' ? 'black' : 'white';
  }

  private toBoardMove(uci: string): BoardMove | null {
    if (!/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(uci)) {
      return null;
    }

    return { from: uci.slice(0, 2), to: uci.slice(2, 4) };
  }

  private compareMovesByWinningChance(
    left: RecommendedMove,
    right: RecommendedMove,
    winningSide: 'white' | 'black',
  ): number {
    const leftChance = left[winningSide];
    const rightChance = right[winningSide];

    if (leftChance !== null && rightChance === null) {
      return -1;
    }

    if (leftChance === null && rightChance !== null) {
      return 1;
    }

    if (leftChance !== null && rightChance !== null && leftChance !== rightChance) {
      if (left.relevant !== right.relevant) {
        return left.relevant ? -1 : 1;
      }

      return rightChance - leftChance;
    }

    if (left.relevant !== right.relevant) {
      return left.relevant ? -1 : 1;
    }

    return (right.games ?? -1) - (left.games ?? -1);
  }
}
