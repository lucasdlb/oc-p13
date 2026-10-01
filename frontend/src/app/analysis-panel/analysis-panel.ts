import { Component, computed, input, output, signal } from '@angular/core';
import { DecimalPipe, PercentPipe } from '@angular/common';

import { AnalyzePositionResponse, RecommendedMove } from '../models/analysis';

@Component({
  selector: 'app-analysis-panel',
  imports: [DecimalPipe, PercentPipe],
  templateUrl: './analysis-panel.html',
  styleUrl: './analysis-panel.css',
})
export class AnalysisPanelComponent {
  readonly analysis = input<AnalyzePositionResponse | null>(null);
  readonly fen = input('');
  readonly ratingMin = input(0);
  readonly ratingMax = input(2500);
  readonly ratingBuckets = input<number[]>([]);
  readonly ratingMinChange = output<number>();
  readonly ratingMaxChange = output<number>();
  readonly loading = input(false);
  readonly error = input<string | null>(null);
  readonly activeExplorer = signal<'lichess' | 'masters'>('lichess');

  readonly sortedRecommendedMoves = computed(() => {
    const moves = this.analysis()?.recommended_moves ?? [];
    const winningSide = this.sideToMove() === 'black' ? 'black' : 'white';

    return [...moves].sort((left, right) =>
      this.compareMovesByWinningChance(left, right, winningSide),
    );
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

  sourceConfidenceTotal(): number | null {
    const total = this.analysis()?.source_confidence['total_games'];
    return typeof total === 'number' ? total : null;
  }

  sourceConfidenceLabel(): string {
    const lowConfidence = this.analysis()?.source_confidence['low_confidence'];
    return lowConfidence === true ? 'Echantillon faible' : 'Echantillon suffisant';
  }

  stockfishLabel(): string {
    const status = this.analysis()?.stockfish?.['status'];
    if (status === 'ok') {
      return 'Evaluation disponible';
    }

    if (status === 'unavailable') {
      return `Indisponible (${this.analysis()?.stockfish?.['reason'] ?? 'raison inconnue'})`;
    }

    return 'Evaluation indisponible';
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

  ratingRangeLabel(): string {
    const min = Math.min(this.ratingMin(), this.ratingMax());
    const max = Math.max(this.ratingMin(), this.ratingMax());
    return min === max ? `bucket ${min}` : `${min}-${max}`;
  }

  ratingGroupsLabel(): string {
    const min = Math.min(this.ratingMin(), this.ratingMax());
    const max = Math.max(this.ratingMin(), this.ratingMax());
    const groups = min === max
      ? [min]
      : this.ratingBuckets().filter((bucket) => min <= bucket && bucket < max);
    return groups.length ? groups.join(', ') : 'aucun';
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
