import { Component, EventEmitter, input, Output } from '@angular/core';

import { PedagogicalLevel } from '../models/analysis';

@Component({
  selector: 'app-level-selector',
  templateUrl: './level-selector.html',
  styleUrl: './level-selector.css',
})
export class LevelSelectorComponent {
  readonly level = input.required<PedagogicalLevel>();

  @Output() readonly levelChange = new EventEmitter<PedagogicalLevel>();

  readonly levels: Array<{ value: PedagogicalLevel; label: string }> = [
    { value: 'debutant', label: 'Debutant' },
    { value: 'intermediaire', label: 'Intermediaire' },
    { value: 'avance', label: 'Avance' },
  ];
}
