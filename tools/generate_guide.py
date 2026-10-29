# Usage: python tools/generate_guide.py moondistribution/templates/moondistribution/guide
"""Generates moondistribution/templates/moondistribution/guide/<lang>.html for all AA languages.

Each text may contain Django template code; `s` is the settings object, `fleet_tracker` a bool.
"""
import os
import sys

OUT = sys.argv[1]

# Django snippets used in all languages
V = {
    "days": "{{ s.application_days }}",
    "wishes": "{{ s.max_wishes }}",
    "maxm": "{{ s.max_moons_per_corp }}",
    "wp": "{{ s.weight_pvp }}",
    "wf": "{{ s.weight_fleet }}",
    "wm": "{{ s.weight_members }}",
    "wa": "{{ s.weight_activity }}",
    "act": "{{ s.active_days }}",
    "bm": "{{ s.bonus_no_moon }}",
    "br": "{{ s.bonus_no_r32 }}",
    "r32": "{{ s.max_r32_per_corp }}",
    "r16": "{{ s.max_r16_per_corp }}",
    "prob": "{{ s.probation_months }}",
}


def chip(r):
    """Rarity chip as used in the app."""
    return f'<span class="md-chip md-r{r}">R{r}</span>'


T = {}

T["en"] = dict(
    title="How the moon distribution works",
    footer="This page always shows the current settings of the Mining Officers.",
    sections=[
        ("1. What is it?",
         f"""<p>Every few months the alliance re-distributes its moons. Corps apply for the moons they want,
         the Auth rates every corp by its activity and assigns the moons <strong>automatically and transparently</strong>.
         {{% if s.exclude_r64 %}}{chip(64)} moons stay with the alliance and are not distributed.{{% endif %}}</p>"""),
        ("2. Timeline",
         f"""<ol>
         <li>The Mining Officers prepare a round and open it.</li>
         <li>From then on applications are open for <strong>{V['days']} days</strong>. You can change your application at any time until the deadline.</li>
         <li>When the time is up, the round is evaluated and distributed <strong>exactly once</strong>, automatically.</li>
         <li>Everyone who applied gets an Auth notification with the result. The full ranking is visible on the round page.</li>
         </ol>"""),
        ("3. Who can apply?",
         """<p>The <strong>CEO</strong>{% if s.allow_directors %} or a <strong>director</strong>{% endif %} of an alliance corp – one application per corp.
         {% if s.allow_directors %}Directors are recognised via Corptools, so the character needs an active Corptools audit.{% endif %}</p>
         {% if s.probation_months %}<p>Your corp must have been in the alliance for at least <strong>{{ s.probation_months }} months</strong> (counted from its last join). Corps that are still in their probation can't apply; the Mining Officers can make an exception.</p>{% endif %}"""),
        ("4. How to apply",
         f"""<ol>
         <li>Open <em>Moon Distribution → Rounds</em> and click <em>Apply</em> next to your corp.</li>
         <li>Tick every moon your corp wants – up to <strong>{V['wishes']}</strong>. The moons are grouped in tabs per region; your selection counts across all tabs.</li>
         <li>Click a column header to sort (e.g. by rarity or by the share of the valuable ore), Shift+click adds a second sort level.</li>
         <li>Save. All ticked moons count the same – there is no ranking.</li>
         </ol>
         <p>Colours: {chip(32)} {chip(16)} {chip(8)} {chip(4)}. The chips next to a moon show its ores and their share,
         <em>Best %</em> is the share of the most valuable ore of the moon's class.</p>"""),
        ("5. How corps are rated",
         f"""<p>Activity is measured for the period shown on the round (usually the last ~6 months).
         Each criterion is scaled from 0 to 100 against the best applying corp, then the weighted average is your score.</p>
         <table class="table table-sm w-auto">
         <thead><tr><th>Criterion</th><th>Source</th><th class="text-end">Weight</th></tr></thead>
         <tbody>
         {{% if s.weight_pvp %}}<tr><td>PvP</td><td>Ships destroyed by your corp (zKillboard)</td><td class="text-end">{V['wp']}</td></tr>{{% endif %}}
         {{% if s.weight_fleet %}}<tr><td>Fleets</td><td>Fleet participations (FAT links)</td><td class="text-end">{V['wf']}</td></tr>{{% endif %}}
         {{% if s.weight_members %}}<tr><td>Active members</td><td>Players whose main is in your corp and who logged in within the last {V['act']} days</td><td class="text-end">{V['wm']}</td></tr>{{% endif %}}
         {{% if s.weight_activity %}}<tr><td>Activity rate</td><td>Share of all characters in your corp (EVE member count) that logged in within the last {V['act']} days – characters that are not registered in the Auth count as inactive</td><td class="text-end">{V['wa']}</td></tr>{{% endif %}}
         </tbody></table>
         {{% if s.per_member %}}<p>PvP and fleets are counted <strong>per active member</strong>, so small but very active corps can keep up with big ones.</p>{{% endif %}}
         <p>Everything counts for the corp of the player's <strong>main character</strong> – alts in other corps count for the main's corp.</p>"""),
        ("6. Bonus points",
         f"""<ul>
         {{% if s.bonus_no_moon %}}<li><strong>+{V['bm']}</strong> if your corp applied in the previous round and got no moon.</li>{{% endif %}}
         {{% if s.bonus_no_r32 %}}<li><strong>+{V['br']}</strong> if your corp got moons in the previous round, but no {chip(32)}.</li>{{% endif %}}
         <li>The Mining Officers can give extra points (or deduct points) to a corp – always with a reason that everyone can see on the round page.</li>
         </ul>"""),
        ("7. How the moons are assigned",
         f"""<ol>
         <li>All applying corps are sorted by their total score (on a tie, the earlier application wins).</li>
         <li>In order, every corp gets <strong>one</strong> moon: the best of its ticked moons that is still free (rarity first, then share of the valuable ore).</li>
         <li>Then the next pass starts with the best corp again – until every corp has <strong>{V['maxm']}</strong> moons or none of its moons is free any more.</li>
         </ol>
         <p>Limits per corp and round:
         {{% if s.max_r32_per_corp is not None %}}max. <strong>{V['r32']}</strong> × {chip(32)}{{% endif %}}
         {{% if s.max_r16_per_corp is not None %}}, max. <strong>{V['r16']}</strong> × {chip(16)}{{% endif %}}
         – if your corp reached a limit, the next free moon of a different class is taken instead.</p>"""),
        ("8. Tips",
         """<ul>
         <li>Tick enough moons – if all of your moons are taken before it is your turn, your corp gets nothing.</li>
         <li>Make sure all your members have registered their characters in the Auth – only registered players count as active members.</li>
         <li>Fly fleets with FAT links and fight – that is what counts most.</li>
         </ul>"""),
    ],
)

T["de"] = dict(
    title="So funktioniert die Moon Distribution",
    footer="Diese Seite zeigt immer die aktuellen Einstellungen der Mining Officer.",
    sections=[
        ("1. Worum geht es?",
         f"""<p>Alle paar Monate verteilt die Allianz ihre Monde neu. Die Corps bewerben sich auf die Monde, die sie haben möchten,
         die Auth bewertet jede Corp nach ihrer Aktivität und vergibt die Monde <strong>automatisch und nachvollziehbar</strong>.
         {{% if s.exclude_r64 %}}{chip(64)}-Monde behält die Allianz, sie werden nicht verteilt.{{% endif %}}</p>"""),
        ("2. Ablauf",
         f"""<ol>
         <li>Die Mining Officer bereiten eine Runde vor und öffnen sie.</li>
         <li>Ab dann läuft die Bewerbung <strong>{V['days']} Tage</strong>. Bis zum Schluss könnt ihr eure Bewerbung jederzeit ändern.</li>
         <li>Danach wird die Runde automatisch ausgewertet und <strong>genau einmal</strong> verteilt.</li>
         <li>Alle Bewerber bekommen eine Auth-Benachrichtigung mit dem Ergebnis. Die komplette Rangliste steht auf der Rundenseite.</li>
         </ol>"""),
        ("3. Wer darf sich bewerben?",
         """<p>Der <strong>CEO</strong>{% if s.allow_directors %} oder ein <strong>Direktor</strong>{% endif %} einer Allianz-Corp – eine Bewerbung pro Corp.
         {% if s.allow_directors %}Direktoren werden über Corptools erkannt, der Charakter braucht also einen aktiven Corptools-Audit.{% endif %}</p>
         {% if s.probation_months %}<p>Eure Corp muss mindestens <strong>{{ s.probation_months }} Monate</strong> in der Allianz sein (gezählt ab dem letzten Beitritt). Corps in der Probezeit können sich nicht bewerben; die Mining Officer können eine Ausnahme machen.</p>{% endif %}"""),
        ("4. So bewerbt ihr euch",
         f"""<ol>
         <li>Öffnet <em>Moon Distribution → Runden</em> und klickt bei eurer Corp auf <em>Bewerben</em>.</li>
         <li>Hakt alle Monde an, die eure Corp möchte – bis zu <strong>{V['wishes']}</strong>. Die Monde sind in Tabs nach Region sortiert, eure Auswahl gilt über alle Tabs.</li>
         <li>Ein Klick auf eine Spaltenüberschrift sortiert (z. B. nach Rarity oder nach dem Anteil des wertvollen Erzes), Shift+Klick fügt eine zweite Sortierstufe hinzu.</li>
         <li>Speichern. Alle angehakten Monde zählen gleich – es gibt keine Rangfolge.</li>
         </ol>
         <p>Farben: {chip(32)} {chip(16)} {chip(8)} {chip(4)}. Die Chips neben einem Mond zeigen seine Erze und deren Anteil,
         <em>Bester %</em> ist der Anteil des wertvollsten Erzes der Mondklasse.</p>"""),
        ("5. So werden die Corps bewertet",
         f"""<p>Gemessen wird die Aktivität im Zeitraum, der bei der Runde angegeben ist (meist die letzten ~6 Monate).
         Jedes Kriterium wird gegen die beste bewerbende Corp auf 0 bis 100 skaliert, der gewichtete Durchschnitt ergibt eure Punkte.</p>
         <table class="table table-sm w-auto">
         <thead><tr><th>Kriterium</th><th>Quelle</th><th class="text-end">Gewicht</th></tr></thead>
         <tbody>
         {{% if s.weight_pvp %}}<tr><td>PvP</td><td>Von eurer Corp zerstörte Schiffe (zKillboard)</td><td class="text-end">{V['wp']}</td></tr>{{% endif %}}
         {{% if s.weight_fleet %}}<tr><td>Fleets</td><td>Fleet-Teilnahmen (FAT-Links)</td><td class="text-end">{V['wf']}</td></tr>{{% endif %}}
         {{% if s.weight_members %}}<tr><td>Aktive Mitglieder</td><td>Spieler, deren Main in eurer Corp ist und die sich in den letzten {V['act']} Tagen eingeloggt haben</td><td class="text-end">{V['wm']}</td></tr>{{% endif %}}
         {{% if s.weight_activity %}}<tr><td>Aktivquote</td><td>Anteil aller Charaktere in eurer Corp (Mitgliederzahl laut EVE), die sich in den letzten {V['act']} Tagen eingeloggt haben – Charaktere, die nicht in der Auth registriert sind, zählen als inaktiv</td><td class="text-end">{V['wa']}</td></tr>{{% endif %}}
         </tbody></table>
         {{% if s.per_member %}}<p>PvP und Fleets zählen <strong>pro aktivem Mitglied</strong>, damit kleine, aber sehr aktive Corps mit großen mithalten können.</p>{{% endif %}}
         <p>Alles zählt für die Corp des <strong>Main-Charakters</strong> – Alts in anderen Corps zählen für die Corp des Mains.</p>"""),
        ("6. Bonuspunkte",
         f"""<ul>
         {{% if s.bonus_no_moon %}}<li><strong>+{V['bm']}</strong>, wenn sich eure Corp in der letzten Runde beworben und keinen Mond bekommen hat.</li>{{% endif %}}
         {{% if s.bonus_no_r32 %}}<li><strong>+{V['br']}</strong>, wenn eure Corp in der letzten Runde Monde, aber keinen {chip(32)} bekommen hat.</li>{{% endif %}}
         <li>Die Mining Officer können einer Corp Zusatzpunkte geben (oder abziehen) – immer mit einer Begründung, die alle auf der Rundenseite sehen.</li>
         </ul>"""),
        ("7. So werden die Monde vergeben",
         f"""<ol>
         <li>Alle bewerbenden Corps werden nach ihren Gesamtpunkten sortiert (bei Gleichstand gewinnt die frühere Bewerbung).</li>
         <li>Der Reihe nach bekommt jede Corp <strong>einen</strong> Mond: den besten ihrer angehakten Monde, der noch frei ist (zuerst Rarity, dann Anteil des wertvollen Erzes).</li>
         <li>Dann beginnt der nächste Durchgang wieder bei der besten Corp – bis jede Corp <strong>{V['maxm']}</strong> Monde hat oder keiner ihrer Monde mehr frei ist.</li>
         </ol>
         <p>Limits pro Corp und Runde:
         {{% if s.max_r32_per_corp is not None %}}max. <strong>{V['r32']}</strong> × {chip(32)}{{% endif %}}
         {{% if s.max_r16_per_corp is not None %}}, max. <strong>{V['r16']}</strong> × {chip(16)}{{% endif %}}
         – ist ein Limit erreicht, bekommt eure Corp stattdessen den nächsten freien Mond einer anderen Klasse.</p>"""),
        ("8. Tipps",
         """<ul>
         <li>Hakt genug Monde an – sind alle eure Monde vergeben, bevor ihr dran seid, geht eure Corp leer aus.</li>
         <li>Sorgt dafür, dass alle Mitglieder ihre Charaktere in der Auth registriert haben – nur registrierte Spieler zählen als aktive Mitglieder.</li>
         <li>Fliegt Fleets mit FAT-Links und kämpft – das zählt am meisten.</li>
         </ul>"""),
    ],
)


def build(lang, title, footer, h, t):
    """Build a language from a heading list h and text dict t (same structure for every language)."""
    T[lang] = dict(title=title, footer=footer, sections=[
        (h[0], f"""<p>{t['intro']} {{% if s.exclude_r64 %}}{chip(64)} {t['r64']}{{% endif %}}</p>"""),
        (h[1], f"""<ol><li>{t['tl1']}</li><li>{t['tl2']}</li><li>{t['tl3']}</li><li>{t['tl4']}</li></ol>"""),
        (h[2], f"""<p>{t['who']}{{% if s.allow_directors %}} {t['who_dir']}{{% endif %}}</p>
         {{% if s.probation_months %}}<p>{t['prob']}</p>{{% endif %}}"""),
        (h[3], f"""<ol><li>{t['ap1']}</li><li>{t['ap2']}</li><li>{t['ap3']}</li><li>{t['ap4']}</li></ol>
         <p>{t['colors']} {chip(32)} {chip(16)} {chip(8)} {chip(4)}. {t['chips']}</p>"""),
        (h[4], f"""<p>{t['rate']}</p>
         <table class="table table-sm w-auto">
         <thead><tr><th>{t['c_crit']}</th><th>{t['c_src']}</th><th class="text-end">{t['c_w']}</th></tr></thead>
         <tbody>
         {{% if s.weight_pvp %}}<tr><td>PvP</td><td>{t['src_pvp']}</td><td class="text-end">{V['wp']}</td></tr>{{% endif %}}
         {{% if s.weight_fleet %}}<tr><td>{t['n_fleet']}</td><td>{t['src_fleet']}</td><td class="text-end">{V['wf']}</td></tr>{{% endif %}}
         {{% if s.weight_members %}}<tr><td>{t['n_mem']}</td><td>{t['src_mem']}</td><td class="text-end">{V['wm']}</td></tr>{{% endif %}}
         {{% if s.weight_activity %}}<tr><td>{t['n_rate']}</td><td>{t['src_rate']}</td><td class="text-end">{V['wa']}</td></tr>{{% endif %}}
         </tbody></table>
         {{% if s.per_member %}}<p>{t['per_member']}</p>{{% endif %}}
         <p>{t['main']}</p>"""),
        (h[5], f"""<ul>
         {{% if s.bonus_no_moon %}}<li><strong>+{V['bm']}</strong> {t['b_moon']}</li>{{% endif %}}
         {{% if s.bonus_no_r32 %}}<li><strong>+{V['br']}</strong> {t['b_r32']} {chip(32)}.</li>{{% endif %}}
         <li>{t['b_manual']}</li></ul>"""),
        (h[6], f"""<ol><li>{t['d1']}</li><li>{t['d2']}</li><li>{t['d3']}</li></ol>
         <p>{t['lim']}
         {{% if s.max_r32_per_corp is not None %}}max. <strong>{V['r32']}</strong> × {chip(32)}{{% endif %}}
         {{% if s.max_r16_per_corp is not None %}}, max. <strong>{V['r16']}</strong> × {chip(16)}{{% endif %}}
         – {t['lim2']}</p>"""),
        (h[7], f"""<ul><li>{t['tip1']}</li><li>{t['tip2']}</li><li>{t['tip3']}</li></ul>"""),
    ])


# ---------------------------------------------------------------- Spanish
build("es", "Cómo funciona el reparto de lunas", "Esta página muestra siempre la configuración actual de los Mining Officers.",
      ["1. ¿De qué se trata?", "2. Calendario", "3. ¿Quién puede solicitar?", "4. Cómo solicitar",
       "5. Cómo se evalúa a las corporaciones", "6. Puntos extra", "7. Cómo se asignan las lunas", "8. Consejos"],
      dict(
          intro="Cada pocos meses la alianza reparte de nuevo sus lunas. Las corporaciones solicitan las lunas que quieren, el Auth evalúa a cada corp por su actividad y asigna las lunas de forma <strong>automática y transparente</strong>.",
          r64="lunas se quedan en la alianza y no se reparten.",
          tl1="Los Mining Officers preparan una ronda y la abren.",
          tl2=f"A partir de ese momento las solicitudes están abiertas durante <strong>{V['days']} días</strong>. Podéis cambiar vuestra solicitud en cualquier momento hasta el cierre.",
          tl3="Al terminar el plazo, la ronda se evalúa y se reparte automáticamente <strong>una sola vez</strong>.",
          tl4="Todos los solicitantes reciben una notificación del Auth con el resultado. La clasificación completa está en la página de la ronda.",
          who="El <strong>CEO</strong> de una corp de la alianza – una solicitud por corp.",
          who_dir="También pueden solicitar los <strong>directores</strong>; se reconocen a través de Corptools, por lo que el personaje necesita una auditoría de Corptools activa.",
          prob=f"Vuestra corp debe llevar al menos <strong>{V['prob']} meses</strong> en la alianza (contados desde su último ingreso). Las corps en periodo de prueba no pueden solicitar; los Mining Officers pueden hacer una excepción.",
          ap1="Abrid <em>Moon Distribution → Rondas</em> y haced clic en <em>Solicitar</em> junto a vuestra corp.",
          ap2=f"Marcad todas las lunas que quiere vuestra corp – hasta <strong>{V['wishes']}</strong>. Las lunas están agrupadas en pestañas por región; la selección cuenta en todas las pestañas.",
          ap3="Haced clic en un encabezado de columna para ordenar (p. ej. por rareza o por el porcentaje del mineral valioso); Mayús+clic añade un segundo nivel de orden.",
          ap4="Guardad. Todas las lunas marcadas cuentan igual – no hay orden de prioridad.",
          colors="Colores:",
          chips="Las etiquetas junto a una luna muestran sus minerales y su porcentaje; <em>Mejor %</em> es el porcentaje del mineral más valioso de la clase de la luna.",
          rate="Se mide la actividad en el periodo indicado en la ronda (normalmente los últimos ~6 meses). Cada criterio se escala de 0 a 100 respecto a la mejor corp solicitante; la media ponderada es vuestra puntuación.",
          c_crit="Criterio", c_src="Fuente", c_w="Peso",
          src_pvp="Naves destruidas por vuestra corp (zKillboard)", n_fleet="Flotas", src_fleet="Participación en flotas (enlaces FAT)",
          n_mem="Miembros activos", src_mem=f"Jugadores cuyo personaje principal está en vuestra corp y que han entrado en los últimos {V['act']} días",
          n_rate="Tasa de actividad", src_rate=f"Porcentaje de todos los personajes de vuestra corp (número de miembros según EVE) que han entrado en los últimos {V['act']} días – los personajes no registrados en el Auth cuentan como inactivos",
          per_member="PvP y flotas se cuentan <strong>por miembro activo</strong>, para que las corps pequeñas pero muy activas puedan competir con las grandes.",
          main="Todo cuenta para la corp del <strong>personaje principal</strong>: los alts en otras corps cuentan para la corp del principal.",
          b_moon="si vuestra corp solicitó en la ronda anterior y no recibió ninguna luna.",
          b_r32="si vuestra corp recibió lunas en la ronda anterior, pero ninguna",
          b_manual="Los Mining Officers pueden dar puntos extra (o restar puntos) a una corp, siempre con un motivo visible para todos en la página de la ronda.",
          d1="Todas las corps solicitantes se ordenan por su puntuación total (en caso de empate gana la solicitud más temprana).",
          d2="Por turnos, cada corp recibe <strong>una</strong> luna: la mejor de sus lunas marcadas que siga libre (primero la rareza, luego el porcentaje del mineral valioso).",
          d3=f"Después empieza la siguiente vuelta otra vez con la mejor corp, hasta que cada corp tenga <strong>{V['maxm']}</strong> lunas o ya no quede libre ninguna de sus lunas.",
          lim="Límites por corp y ronda:", lim2="si vuestra corp alcanza un límite, recibe en su lugar la siguiente luna libre de otra clase.",
          tip1="Marcad suficientes lunas: si todas vuestras lunas están asignadas antes de vuestro turno, vuestra corp se queda sin nada.",
          tip2="Aseguraos de que todos los miembros han registrado sus personajes en el Auth: solo los jugadores registrados cuentan como miembros activos.",
          tip3="Volad en flotas con enlaces FAT y combatid: eso es lo que más cuenta.",
      ))

# ---------------------------------------------------------------- Italian
build("it", "Come funziona la distribuzione delle lune", "Questa pagina mostra sempre le impostazioni attuali dei Mining Officer.",
      ["1. Di cosa si tratta?", "2. Svolgimento", "3. Chi può candidarsi?", "4. Come candidarsi",
       "5. Come vengono valutate le corp", "6. Punti bonus", "7. Come vengono assegnate le lune", "8. Consigli"],
      dict(
          intro="Ogni qualche mese l'alleanza ridistribuisce le sue lune. Le corp si candidano per le lune che desiderano, l'Auth valuta ogni corp in base alla sua attività e assegna le lune in modo <strong>automatico e trasparente</strong>.",
          r64="lune restano all'alleanza e non vengono distribuite.",
          tl1="I Mining Officer preparano un round e lo aprono.",
          tl2=f"Da quel momento le candidature restano aperte per <strong>{V['days']} giorni</strong>. Potete modificare la vostra candidatura in qualsiasi momento fino alla scadenza.",
          tl3="Allo scadere del tempo il round viene valutato e distribuito automaticamente <strong>una sola volta</strong>.",
          tl4="Tutti i candidati ricevono una notifica dell'Auth con il risultato. La classifica completa è visibile nella pagina del round.",
          who="Il <strong>CEO</strong> di una corp dell'alleanza – una candidatura per corp.",
          who_dir="Possono candidarsi anche i <strong>direttori</strong>; vengono riconosciuti tramite Corptools, quindi il personaggio deve avere un audit Corptools attivo.",
          prob=f"La vostra corp deve far parte dell'alleanza da almeno <strong>{V['prob']} mesi</strong> (contati dall'ultimo ingresso). Le corp ancora in periodo di prova non possono candidarsi; i Mining Officer possono fare un'eccezione.",
          ap1="Aprite <em>Moon Distribution → Round</em> e cliccate su <em>Candidati</em> accanto alla vostra corp.",
          ap2=f"Spuntate tutte le lune che la vostra corp desidera – fino a <strong>{V['wishes']}</strong>. Le lune sono raggruppate in schede per regione; la selezione vale per tutte le schede.",
          ap3="Cliccate sull'intestazione di una colonna per ordinare (ad es. per rarità o per la quota del minerale prezioso); Maiusc+clic aggiunge un secondo livello di ordinamento.",
          ap4="Salvate. Tutte le lune spuntate valgono allo stesso modo – non c'è una classifica di priorità.",
          colors="Colori:",
          chips="Le etichette accanto a una luna mostrano i suoi minerali e la loro quota; <em>Miglior %</em> è la quota del minerale più prezioso della classe della luna.",
          rate="Viene misurata l'attività nel periodo indicato nel round (di solito gli ultimi ~6 mesi). Ogni criterio viene scalato da 0 a 100 rispetto alla migliore corp candidata; la media ponderata è il vostro punteggio.",
          c_crit="Criterio", c_src="Fonte", c_w="Peso",
          src_pvp="Navi distrutte dalla vostra corp (zKillboard)", n_fleet="Flotte", src_fleet="Partecipazioni alle flotte (link FAT)",
          n_mem="Membri attivi", src_mem=f"Giocatori il cui personaggio principale è nella vostra corp e che hanno effettuato l'accesso negli ultimi {V['act']} giorni",
          n_rate="Tasso di attività", src_rate=f"Percentuale di tutti i personaggi della vostra corp (numero di membri secondo EVE) che hanno effettuato l'accesso negli ultimi {V['act']} giorni – i personaggi non registrati nell'Auth contano come inattivi",
          per_member="PvP e flotte vengono contati <strong>per membro attivo</strong>, così le corp piccole ma molto attive possono competere con quelle grandi.",
          main="Tutto conta per la corp del <strong>personaggio principale</strong>: gli alt in altre corp contano per la corp del principale.",
          b_moon="se la vostra corp si è candidata nel round precedente e non ha ricevuto nessuna luna.",
          b_r32="se la vostra corp ha ricevuto lune nel round precedente, ma nessuna",
          b_manual="I Mining Officer possono assegnare punti extra (o togliere punti) a una corp – sempre con una motivazione visibile a tutti nella pagina del round.",
          d1="Tutte le corp candidate vengono ordinate per punteggio totale (a parità vince la candidatura più vecchia).",
          d2="A turno ogni corp riceve <strong>una</strong> luna: la migliore tra le sue lune spuntate ancora libere (prima la rarità, poi la quota del minerale prezioso).",
          d3=f"Poi inizia il giro successivo, di nuovo dalla corp migliore – finché ogni corp ha <strong>{V['maxm']}</strong> lune o nessuna delle sue lune è più libera.",
          lim="Limiti per corp e round:", lim2="se la vostra corp raggiunge un limite, riceve invece la prossima luna libera di un'altra classe.",
          tip1="Spuntate abbastanza lune: se tutte le vostre lune vengono assegnate prima del vostro turno, la vostra corp resta a mani vuote.",
          tip2="Assicuratevi che tutti i membri abbiano registrato i loro personaggi nell'Auth: solo i giocatori registrati contano come membri attivi.",
          tip3="Volate in flotta con i link FAT e combattete: è ciò che conta di più.",
      ))

# ---------------------------------------------------------------- French
build("fr", "Comment fonctionne la distribution des lunes", "Cette page affiche toujours les réglages actuels des Mining Officers.",
      ["1. De quoi s'agit-il ?", "2. Déroulement", "3. Qui peut postuler ?", "4. Comment postuler",
       "5. Comment les corps sont évaluées", "6. Points bonus", "7. Comment les lunes sont attribuées", "8. Conseils"],
      dict(
          intro="Tous les quelques mois, l'alliance redistribue ses lunes. Les corps postulent pour les lunes qu'elles souhaitent, l'Auth évalue chaque corp selon son activité et attribue les lunes de façon <strong>automatique et transparente</strong>.",
          r64="lunes restent à l'alliance et ne sont pas distribuées.",
          tl1="Les Mining Officers préparent un tour et l'ouvrent.",
          tl2=f"À partir de là, les candidatures sont ouvertes pendant <strong>{V['days']} jours</strong>. Vous pouvez modifier votre candidature à tout moment jusqu'à la clôture.",
          tl3="Une fois le délai écoulé, le tour est évalué et distribué automatiquement, <strong>une seule fois</strong>.",
          tl4="Tous les candidats reçoivent une notification de l'Auth avec le résultat. Le classement complet est visible sur la page du tour.",
          who="Le <strong>CEO</strong> d'une corp de l'alliance – une candidature par corp.",
          who_dir="Les <strong>directeurs</strong> peuvent aussi postuler ; ils sont reconnus via Corptools, le personnage doit donc avoir un audit Corptools actif.",
          prob=f"Votre corp doit faire partie de l'alliance depuis au moins <strong>{V['prob']} mois</strong> (à compter de sa dernière adhésion). Les corps encore en période d'essai ne peuvent pas postuler ; les Mining Officers peuvent faire une exception.",
          ap1="Ouvrez <em>Moon Distribution → Tours</em> et cliquez sur <em>Postuler</em> à côté de votre corp.",
          ap2=f"Cochez toutes les lunes que votre corp souhaite – jusqu'à <strong>{V['wishes']}</strong>. Les lunes sont regroupées par région dans des onglets ; votre sélection vaut pour tous les onglets.",
          ap3="Cliquez sur un en-tête de colonne pour trier (par ex. par rareté ou par la part du minerai précieux) ; Maj+clic ajoute un second niveau de tri.",
          ap4="Enregistrez. Toutes les lunes cochées comptent de la même façon – il n'y a pas d'ordre de priorité.",
          colors="Couleurs :",
          chips="Les étiquettes à côté d'une lune indiquent ses minerais et leur part ; <em>Meilleur %</em> est la part du minerai le plus précieux de la classe de la lune.",
          rate="L'activité est mesurée sur la période indiquée pour le tour (généralement les ~6 derniers mois). Chaque critère est ramené sur une échelle de 0 à 100 par rapport à la meilleure corp candidate ; la moyenne pondérée donne votre score.",
          c_crit="Critère", c_src="Source", c_w="Poids",
          src_pvp="Vaisseaux détruits par votre corp (zKillboard)", n_fleet="Flottes", src_fleet="Participations aux flottes (liens FAT)",
          n_mem="Membres actifs", src_mem=f"Joueurs dont le personnage principal est dans votre corp et qui se sont connectés au cours des {V['act']} derniers jours",
          n_rate="Taux d'activité", src_rate=f"Part de tous les personnages de votre corp (nombre de membres selon EVE) qui se sont connectés au cours des {V['act']} derniers jours – les personnages non enregistrés dans l'Auth comptent comme inactifs",
          per_member="Le PvP et les flottes sont comptés <strong>par membre actif</strong>, pour que les petites corps très actives puissent rivaliser avec les grandes.",
          main="Tout compte pour la corp du <strong>personnage principal</strong> : les alts dans d'autres corps comptent pour la corp du principal.",
          b_moon="si votre corp a postulé au tour précédent et n'a obtenu aucune lune.",
          b_r32="si votre corp a obtenu des lunes au tour précédent, mais aucune",
          b_manual="Les Mining Officers peuvent accorder des points supplémentaires (ou en retirer) à une corp – toujours avec une raison visible par tous sur la page du tour.",
          d1="Toutes les corps candidates sont classées selon leur score total (en cas d'égalité, la candidature la plus ancienne l'emporte).",
          d2="Chacune son tour, chaque corp reçoit <strong>une</strong> lune : la meilleure de ses lunes cochées encore libre (d'abord la rareté, puis la part du minerai précieux).",
          d3=f"Puis le tour suivant recommence avec la meilleure corp – jusqu'à ce que chaque corp ait <strong>{V['maxm']}</strong> lunes ou qu'aucune de ses lunes ne soit encore libre.",
          lim="Limites par corp et par tour :", lim2="si votre corp atteint une limite, elle reçoit à la place la prochaine lune libre d'une autre classe.",
          tip1="Cochez assez de lunes : si toutes vos lunes sont attribuées avant votre tour, votre corp n'obtient rien.",
          tip2="Veillez à ce que tous les membres aient enregistré leurs personnages dans l'Auth : seuls les joueurs enregistrés comptent comme membres actifs.",
          tip3="Volez en flotte avec des liens FAT et combattez – c'est ce qui compte le plus.",
      ))

# ---------------------------------------------------------------- Dutch
build("nl", "Zo werkt de maanverdeling", "Deze pagina toont altijd de actuele instellingen van de Mining Officers.",
      ["1. Waar gaat het om?", "2. Verloop", "3. Wie mag zich aanmelden?", "4. Zo meld je je aan",
       "5. Zo worden corps beoordeeld", "6. Bonuspunten", "7. Zo worden de manen toegewezen", "8. Tips"],
      dict(
          intro="Om de paar maanden verdeelt de alliantie haar manen opnieuw. Corps melden zich aan voor de manen die ze willen, de Auth beoordeelt elke corp op activiteit en wijst de manen <strong>automatisch en transparant</strong> toe.",
          r64="manen blijven bij de alliantie en worden niet verdeeld.",
          tl1="De Mining Officers bereiden een ronde voor en openen die.",
          tl2=f"Vanaf dan staan aanmeldingen <strong>{V['days']} dagen</strong> open. Tot de deadline kun je je aanmelding altijd wijzigen.",
          tl3="Als de tijd om is, wordt de ronde automatisch beoordeeld en <strong>precies één keer</strong> verdeeld.",
          tl4="Iedereen die zich heeft aangemeld krijgt een Auth-melding met het resultaat. De volledige ranglijst staat op de rondepagina.",
          who="De <strong>CEO</strong> van een alliantie-corp – één aanmelding per corp.",
          who_dir="Ook <strong>directors</strong> mogen zich aanmelden; zij worden via Corptools herkend, dus het personage heeft een actieve Corptools-audit nodig.",
          prob=f"Jullie corp moet minstens <strong>{V['prob']} maanden</strong> in de alliantie zitten (gerekend vanaf de laatste toetreding). Corps die nog in hun proeftijd zitten, kunnen zich niet aanmelden; de Mining Officers kunnen een uitzondering maken.",
          ap1="Open <em>Moon Distribution → Rondes</em> en klik naast je corp op <em>Aanmelden</em>.",
          ap2=f"Vink alle manen aan die je corp wil – tot <strong>{V['wishes']}</strong>. De manen staan per regio in tabbladen; je selectie geldt voor alle tabbladen.",
          ap3="Klik op een kolomkop om te sorteren (bijv. op zeldzaamheid of op het aandeel van het waardevolle erts); Shift+klik voegt een tweede sorteerniveau toe.",
          ap4="Opslaan. Alle aangevinkte manen tellen even zwaar – er is geen volgorde van voorkeur.",
          colors="Kleuren:",
          chips="De labels naast een maan tonen de ertsen en hun aandeel; <em>Beste %</em> is het aandeel van het waardevolste erts van de maanklasse.",
          rate="Gemeten wordt de activiteit in de periode die bij de ronde staat (meestal de laatste ~6 maanden). Elk criterium wordt geschaald van 0 tot 100 ten opzichte van de beste corp die zich aanmeldt; het gewogen gemiddelde is jullie score.",
          c_crit="Criterium", c_src="Bron", c_w="Gewicht",
          src_pvp="Schepen vernietigd door jullie corp (zKillboard)", n_fleet="Fleets", src_fleet="Deelnames aan fleets (FAT-links)",
          n_mem="Actieve leden", src_mem=f"Spelers van wie de main in jullie corp zit en die in de laatste {V['act']} dagen zijn ingelogd",
          n_rate="Activiteitsgraad", src_rate=f"Aandeel van alle characters in jullie corp (ledenaantal volgens EVE) dat in de laatste {V['act']} dagen is ingelogd – characters die niet in de Auth geregistreerd zijn, tellen als inactief",
          per_member="PvP en fleets tellen <strong>per actief lid</strong>, zodat kleine maar zeer actieve corps kunnen meekomen met grote.",
          main="Alles telt voor de corp van het <strong>main-personage</strong> – alts in andere corps tellen voor de corp van de main.",
          b_moon="als jullie corp zich in de vorige ronde heeft aangemeld en geen maan heeft gekregen.",
          b_r32="als jullie corp in de vorige ronde manen heeft gekregen, maar geen",
          b_manual="De Mining Officers kunnen een corp extra punten geven (of aftrekken) – altijd met een reden die iedereen op de rondepagina ziet.",
          d1="Alle corps die zich hebben aangemeld worden gesorteerd op hun totaalscore (bij gelijkspel wint de eerdere aanmelding).",
          d2="Om de beurt krijgt elke corp <strong>één</strong> maan: de beste van haar aangevinkte manen die nog vrij is (eerst zeldzaamheid, dan aandeel van het waardevolle erts).",
          d3=f"Daarna begint de volgende ronde weer bij de beste corp – tot elke corp <strong>{V['maxm']}</strong> manen heeft of geen van haar manen nog vrij is.",
          lim="Limieten per corp en ronde:", lim2="bereikt jullie corp een limiet, dan krijgt ze in plaats daarvan de volgende vrije maan van een andere klasse.",
          tip1="Vink genoeg manen aan – zijn al jullie manen weg voordat jullie aan de beurt zijn, dan krijgt jullie corp niets.",
          tip2="Zorg dat alle leden hun personages in de Auth hebben geregistreerd – alleen geregistreerde spelers tellen als actieve leden.",
          tip3="Vlieg fleets met FAT-links en vecht – dat telt het zwaarst.",
      ))

# ---------------------------------------------------------------- Polish
build("pl", "Jak działa podział księżyców", "Ta strona zawsze pokazuje aktualne ustawienia Mining Officerów.",
      ["1. O co chodzi?", "2. Przebieg", "3. Kto może się zgłosić?", "4. Jak się zgłosić",
       "5. Jak oceniane są korporacje", "6. Punkty bonusowe", "7. Jak przydzielane są księżyce", "8. Wskazówki"],
      dict(
          intro="Co kilka miesięcy sojusz na nowo dzieli swoje księżyce. Korporacje zgłaszają się po księżyce, które chcą, Auth ocenia każdą corp według jej aktywności i przydziela księżyce <strong>automatycznie i przejrzyście</strong>.",
          r64="księżyce zostają przy sojuszu i nie są rozdzielane.",
          tl1="Mining Officerowie przygotowują rundę i ją otwierają.",
          tl2=f"Od tego momentu zgłoszenia są otwarte przez <strong>{V['days']} dni</strong>. Do terminu możecie w każdej chwili zmienić zgłoszenie.",
          tl3="Po upływie czasu runda jest automatycznie oceniana i rozdzielana <strong>dokładnie raz</strong>.",
          tl4="Wszyscy zgłaszający dostają powiadomienie w Auth z wynikiem. Pełny ranking jest widoczny na stronie rundy.",
          who="<strong>CEO</strong> korporacji z sojuszu – jedno zgłoszenie na corp.",
          who_dir="Zgłaszać się mogą też <strong>dyrektorzy</strong>; są rozpoznawani przez Corptools, więc postać potrzebuje aktywnego audytu Corptools.",
          prob=f"Wasza corp musi być w sojuszu co najmniej <strong>{V['prob']} mies.</strong> (licząc od ostatniego dołączenia). Corp w okresie próbnym nie mogą składać zgłoszeń; Mining Officerowie mogą zrobić wyjątek.",
          ap1="Otwórzcie <em>Moon Distribution → Rundy</em> i kliknijcie <em>Zgłoś się</em> przy swojej corp.",
          ap2=f"Zaznaczcie wszystkie księżyce, które chce wasza corp – maksymalnie <strong>{V['wishes']}</strong>. Księżyce są pogrupowane w zakładki według regionu; wybór obowiązuje we wszystkich zakładkach.",
          ap3="Kliknięcie nagłówka kolumny sortuje (np. według rzadkości lub udziału cennej rudy); Shift+klik dodaje drugi poziom sortowania.",
          ap4="Zapiszcie. Wszystkie zaznaczone księżyce liczą się tak samo – nie ma kolejności priorytetów.",
          colors="Kolory:",
          chips="Etykiety obok księżyca pokazują jego rudy i ich udział; <em>Najlepszy %</em> to udział najcenniejszej rudy danej klasy księżyca.",
          rate="Mierzona jest aktywność w okresie podanym przy rundzie (zwykle ostatnie ~6 miesięcy). Każde kryterium jest skalowane od 0 do 100 względem najlepszej zgłaszającej się corp; średnia ważona to wasz wynik.",
          c_crit="Kryterium", c_src="Źródło", c_w="Waga",
          src_pvp="Statki zniszczone przez waszą corp (zKillboard)", n_fleet="Floty", src_fleet="Udział we flotach (linki FAT)",
          n_mem="Aktywni członkowie", src_mem=f"Gracze, których główna postać jest w waszej corp i którzy logowali się w ciągu ostatnich {V['act']} dni",
          n_rate="Wskaźnik aktywności", src_rate=f"Odsetek wszystkich postaci w waszej corp (liczba członków według EVE), które logowały się w ciągu ostatnich {V['act']} dni – postacie niezarejestrowane w Auth liczą się jako nieaktywne",
          per_member="PvP i floty liczone są <strong>na aktywnego członka</strong>, aby małe, ale bardzo aktywne korporacje mogły dorównać dużym.",
          main="Wszystko liczy się dla corp <strong>głównej postaci</strong> – alty w innych korporacjach liczą się dla corp maina.",
          b_moon="jeśli wasza corp zgłosiła się w poprzedniej rundzie i nie dostała żadnego księżyca.",
          b_r32="jeśli wasza corp dostała w poprzedniej rundzie księżyce, ale żadnego",
          b_manual="Mining Officerowie mogą dać corp dodatkowe punkty (lub je odjąć) – zawsze z uzasadnieniem widocznym dla wszystkich na stronie rundy.",
          d1="Wszystkie zgłoszone korporacje są sortowane według łącznego wyniku (przy remisie wygrywa wcześniejsze zgłoszenie).",
          d2="Po kolei każda corp dostaje <strong>jeden</strong> księżyc: najlepszy z zaznaczonych, który jest jeszcze wolny (najpierw rzadkość, potem udział cennej rudy).",
          d3=f"Potem zaczyna się kolejna tura, znowu od najlepszej corp – aż każda corp ma <strong>{V['maxm']}</strong> księżyce albo żaden z jej księżyców nie jest już wolny.",
          lim="Limity na corp i rundę:", lim2="jeśli wasza corp osiągnie limit, dostaje zamiast tego następny wolny księżyc innej klasy.",
          tip1="Zaznaczcie wystarczająco dużo księżyców – jeśli wszystkie zostaną rozdane przed waszą kolejką, corp nic nie dostanie.",
          tip2="Upewnijcie się, że wszyscy członkowie zarejestrowali swoje postacie w Auth – tylko zarejestrowani gracze liczą się jako aktywni członkowie.",
          tip3="Latajcie we flotach z linkami FAT i walczcie – to liczy się najbardziej.",
      ))

# ---------------------------------------------------------------- Russian
build("ru", "Как работает распределение лун", "На этой странице всегда показаны текущие настройки Mining Officer'ов.",
      ["1. О чём речь?", "2. Порядок проведения", "3. Кто может подать заявку?", "4. Как подать заявку",
       "5. Как оцениваются корпорации", "6. Бонусные очки", "7. Как распределяются луны", "8. Советы"],
      dict(
          intro="Раз в несколько месяцев альянс заново распределяет свои луны. Корпорации подают заявки на нужные им луны, Auth оценивает каждую корпорацию по её активности и распределяет луны <strong>автоматически и прозрачно</strong>.",
          r64="луны остаются у альянса и не распределяются.",
          tl1="Mining Officer'ы готовят раунд и открывают его.",
          tl2=f"С этого момента приём заявок открыт <strong>{V['days']} дн.</strong> До окончания срока заявку можно менять в любое время.",
          tl3="По истечении срока раунд автоматически оценивается и распределяется <strong>ровно один раз</strong>.",
          tl4="Все подавшие заявку получают уведомление в Auth с результатом. Полный рейтинг виден на странице раунда.",
          who="<strong>CEO</strong> корпорации альянса – одна заявка на корпорацию.",
          who_dir="Подавать заявку могут и <strong>директора</strong>; они определяются через Corptools, поэтому у персонажа должен быть активный аудит Corptools.",
          prob=f"Ваша корпорация должна состоять в альянсе не менее <strong>{V['prob']} мес.</strong> (считая с последнего вступления). Корпорации на испытательном сроке не могут подавать заявки; Mining Officer'ы могут сделать исключение.",
          ap1="Откройте <em>Moon Distribution → Раунды</em> и нажмите <em>Подать заявку</em> рядом со своей корпорацией.",
          ap2=f"Отметьте все луны, которые нужны вашей корпорации – до <strong>{V['wishes']}</strong>. Луны сгруппированы по регионам во вкладках; выбор действует во всех вкладках.",
          ap3="Нажмите на заголовок столбца для сортировки (например, по редкости или по доле ценной руды); Shift+клик добавляет второй уровень сортировки.",
          ap4="Сохраните. Все отмеченные луны равноценны – порядка приоритетов нет.",
          colors="Цвета:",
          chips="Метки рядом с луной показывают её руды и их долю; <em>Лучший %</em> – доля самой ценной руды класса луны.",
          rate="Измеряется активность за период, указанный в раунде (обычно последние ~6 месяцев). Каждый критерий масштабируется от 0 до 100 относительно лучшей корпорации-заявителя; взвешенное среднее – это ваш результат.",
          c_crit="Критерий", c_src="Источник", c_w="Вес",
          src_pvp="Корабли, уничтоженные вашей корпорацией (zKillboard)", n_fleet="Флоты", src_fleet="Участие во флотах (ссылки FAT)",
          n_mem="Активные участники", src_mem=f"Игроки, чей основной персонаж состоит в вашей корпорации и кто заходил в игру за последние {V['act']} дн.",
          n_rate="Доля активных", src_rate=f"Доля всех персонажей вашей корпорации (число участников по данным EVE), заходивших в игру за последние {V['act']} дн. – персонажи, не зарегистрированные в Auth, считаются неактивными",
          per_member="PvP и флоты считаются <strong>на одного активного участника</strong>, чтобы небольшие, но очень активные корпорации могли конкурировать с крупными.",
          main="Всё засчитывается корпорации <strong>основного персонажа</strong> – альты в других корпорациях засчитываются корпорации мейна.",
          b_moon="если ваша корпорация подавала заявку в прошлом раунде и не получила ни одной луны.",
          b_r32="если ваша корпорация получила луны в прошлом раунде, но ни одной",
          b_manual="Mining Officer'ы могут начислить корпорации дополнительные очки (или снять их) – всегда с причиной, которую все видят на странице раунда.",
          d1="Все корпорации-заявители сортируются по общему результату (при равенстве побеждает более ранняя заявка).",
          d2="По очереди каждая корпорация получает <strong>одну</strong> луну: лучшую из отмеченных, которая ещё свободна (сначала редкость, затем доля ценной руды).",
          d3=f"Затем начинается следующий круг, снова с лучшей корпорации – пока у каждой корпорации не будет <strong>{V['maxm']}</strong> лун или пока ни одна из её лун не останется свободной.",
          lim="Лимиты на корпорацию за раунд:", lim2="если ваша корпорация достигла лимита, она получает следующую свободную луну другого класса.",
          tip1="Отмечайте достаточно лун – если все ваши луны разберут до вашей очереди, корпорация ничего не получит.",
          tip2="Убедитесь, что все участники зарегистрировали своих персонажей в Auth – только зарегистрированные игроки считаются активными участниками.",
          tip3="Летайте во флотах с FAT-ссылками и сражайтесь – это важнее всего.",
      ))

# ---------------------------------------------------------------- Ukrainian
build("uk", "Як працює розподіл місяців", "Ця сторінка завжди показує поточні налаштування Mining Officer'ів.",
      ["1. Про що йдеться?", "2. Порядок проведення", "3. Хто може подати заявку?", "4. Як подати заявку",
       "5. Як оцінюються корпорації", "6. Бонусні бали", "7. Як розподіляються місяці", "8. Поради"],
      dict(
          intro="Раз на кілька місяців альянс заново розподіляє свої місяці. Корпорації подають заявки на потрібні місяці, Auth оцінює кожну корпорацію за її активністю та розподіляє місяці <strong>автоматично й прозоро</strong>.",
          r64="місяці залишаються в альянсі й не розподіляються.",
          tl1="Mining Officer'и готують раунд і відкривають його.",
          tl2=f"З цього моменту прийом заявок відкритий <strong>{V['days']} дн.</strong> До кінця терміну заявку можна змінювати будь-коли.",
          tl3="Після закінчення терміну раунд автоматично оцінюється та розподіляється <strong>рівно один раз</strong>.",
          tl4="Усі, хто подав заявку, отримують сповіщення в Auth із результатом. Повний рейтинг видно на сторінці раунду.",
          who="<strong>CEO</strong> корпорації альянсу – одна заявка на корпорацію.",
          who_dir="Подавати заявку можуть і <strong>директори</strong>; їх визначають через Corptools, тому персонаж має мати активний аудит Corptools.",
          prob=f"Ваша корпорація має бути в альянсі щонайменше <strong>{V['prob']} міс.</strong> (рахуючи від останнього вступу). Корпорації на випробувальному терміні не можуть подавати заявки; Mining Officer'и можуть зробити виняток.",
          ap1="Відкрийте <em>Moon Distribution → Раунди</em> і натисніть <em>Подати заявку</em> біля своєї корпорації.",
          ap2=f"Позначте всі місяці, які потрібні вашій корпорації – до <strong>{V['wishes']}</strong>. Місяці згруповані за регіонами у вкладках; вибір діє в усіх вкладках.",
          ap3="Натисніть на заголовок стовпця, щоб відсортувати (наприклад, за рідкістю або часткою цінної руди); Shift+клік додає другий рівень сортування.",
          ap4="Збережіть. Усі позначені місяці рівноцінні – порядку пріоритетів немає.",
          colors="Кольори:",
          chips="Мітки біля місяця показують його руди та їхню частку; <em>Найкращий %</em> – частка найціннішої руди класу місяця.",
          rate="Вимірюється активність за період, указаний у раунді (зазвичай останні ~6 місяців). Кожен критерій масштабується від 0 до 100 відносно найкращої корпорації-заявника; зважене середнє – це ваш результат.",
          c_crit="Критерій", c_src="Джерело", c_w="Вага",
          src_pvp="Кораблі, знищені вашою корпорацією (zKillboard)", n_fleet="Флоти", src_fleet="Участь у флотах (посилання FAT)",
          n_mem="Активні учасники", src_mem=f"Гравці, чий основний персонаж у вашій корпорації і хто заходив у гру за останні {V['act']} дн.",
          n_rate="Частка активних", src_rate=f"Частка всіх персонажів вашої корпорації (кількість учасників за даними EVE), які заходили в гру за останні {V['act']} дн. – персонажі, не зареєстровані в Auth, вважаються неактивними",
          per_member="PvP і флоти рахуються <strong>на одного активного учасника</strong>, щоб невеликі, але дуже активні корпорації могли конкурувати з великими.",
          main="Усе зараховується корпорації <strong>основного персонажа</strong> – альти в інших корпораціях зараховуються корпорації мейна.",
          b_moon="якщо ваша корпорація подавала заявку в минулому раунді й не отримала жодного місяця.",
          b_r32="якщо ваша корпорація отримала місяці в минулому раунді, але жодного",
          b_manual="Mining Officer'и можуть нарахувати корпорації додаткові бали (або зняти їх) – завжди з причиною, яку всі бачать на сторінці раунду.",
          d1="Усі корпорації-заявники сортуються за загальним результатом (за рівності перемагає раніша заявка).",
          d2="По черзі кожна корпорація отримує <strong>один</strong> місяць: найкращий із позначених, який ще вільний (спочатку рідкість, потім частка цінної руди).",
          d3=f"Потім починається наступне коло, знову з найкращої корпорації – доки кожна корпорація не матиме <strong>{V['maxm']}</strong> місяців або жоден із її місяців не залишиться вільним.",
          lim="Ліміти на корпорацію за раунд:", lim2="якщо ваша корпорація досягла ліміту, вона отримує наступний вільний місяць іншого класу.",
          tip1="Позначайте достатньо місяців – якщо всі ваші місяці розберуть до вашої черги, корпорація нічого не отримає.",
          tip2="Переконайтеся, що всі учасники зареєстрували своїх персонажів в Auth – лише зареєстровані гравці вважаються активними учасниками.",
          tip3="Літайте у флотах із FAT-посиланнями та бийтеся – це важить найбільше.",
      ))

# ---------------------------------------------------------------- Japanese
build("ja", "ムーン分配の仕組み", "このページには常にマイニングオフィサーの現在の設定が表示されます。",
      ["1. 概要", "2. 流れ", "3. 申請できるのは？", "4. 申請方法",
       "5. コーポの評価方法", "6. ボーナスポイント", "7. ムーンの割り当て方法", "8. ヒント"],
      dict(
          intro="アライアンスは数か月ごとにムーンを再分配します。各コーポは希望するムーンに申請し、Auth が活動量に基づいて各コーポを評価し、ムーンを<strong>自動的かつ透明に</strong>割り当てます。",
          r64="ムーンはアライアンスが保持し、分配されません。",
          tl1="マイニングオフィサーがラウンドを準備して開始します。",
          tl2=f"開始から<strong>{V['days']}日間</strong>申請を受け付けます。締め切りまではいつでも申請を変更できます。",
          tl3="期間が終わると、ラウンドは自動的に評価され、<strong>一度だけ</strong>分配されます。",
          tl4="申請した全員に結果が Auth の通知で届きます。ランキング全体はラウンドのページで確認できます。",
          who="アライアンス所属コーポの<strong>CEO</strong> – 1コーポにつき1件の申請です。",
          who_dir="<strong>ディレクター</strong>も申請できます。ディレクターは Corptools で判定されるため、キャラクターに有効な Corptools 監査が必要です。",
          prob=f"コーポは同盟に少なくとも<strong>{V['prob']}か月</strong>在籍している必要があります（最後の加入日から数えます）。試用期間中のコーポは申請できません。マイニングオフィサーは例外を認めることができます。",
          ap1="<em>Moon Distribution → ラウンド</em>を開き、自分のコーポの横にある<em>申請</em>をクリックします。",
          ap2=f"コーポが希望するムーンをすべてチェックします（最大<strong>{V['wishes']}</strong>件）。ムーンはリージョンごとのタブに分かれており、選択はすべてのタブで共通です。",
          ap3="列の見出しをクリックすると並べ替えできます（例：レア度や高価値鉱石の割合）。Shift+クリックで2段階目の並べ替えを追加できます。",
          ap4="保存します。チェックしたムーンはすべて同等に扱われ、優先順位はありません。",
          colors="色：",
          chips="ムーンの横のラベルは鉱石とその割合を示します。<em>最高 %</em> はそのムーンのクラスで最も価値の高い鉱石の割合です。",
          rate="ラウンドに表示された期間（通常は直近約6か月）の活動を計測します。各基準は申請コーポの中で最も高いコーポを100として0〜100に換算され、その加重平均がスコアになります。",
          c_crit="基準", c_src="データ元", c_w="重み",
          src_pvp="コーポが撃破した艦船（zKillboard）", n_fleet="フリート", src_fleet="フリート参加（FATリンク）",
          n_mem="アクティブメンバー", src_mem=f"メインキャラクターがコーポに所属し、直近{V['act']}日以内にログインしたプレイヤー",
          n_rate="アクティブ率", src_rate=f"コーポの全キャラクター（EVE上のメンバー数）のうち、直近{V['act']}日以内にログインした割合 – Authに登録されていないキャラクターは非アクティブとして扱われます",
          per_member="PvP とフリートは<strong>アクティブメンバー1人あたり</strong>で計算されるため、小規模でも活発なコーポが大規模コーポと競えます。",
          main="すべて<strong>メインキャラクター</strong>のコーポに加算されます。他コーポにいるオルトもメインのコーポに加算されます。",
          b_moon="前回のラウンドで申請したのにムーンを1つも得られなかった場合。",
          b_r32="前回のラウンドでムーンを得たものの、次のクラスを1つも得られなかった場合：",
          b_manual="マイニングオフィサーはコーポに追加ポイントを与える（または減点する）ことができます。理由は必ずラウンドのページで全員に公開されます。",
          d1="申請したすべてのコーポを合計スコア順に並べます（同点の場合は先に申請したコーポが上位）。",
          d2="順番に各コーポが<strong>1つ</strong>のムーンを受け取ります。チェックしたムーンのうち、まだ空いている最良のもの（まずレア度、次に高価値鉱石の割合）です。",
          d3=f"その後、再び最上位のコーポから次の周回が始まり、各コーポが<strong>{V['maxm']}</strong>個のムーンを得るか、希望ムーンがすべて埋まるまで続きます。",
          lim="1コーポ・1ラウンドあたりの上限：", lim2="上限に達した場合は、代わりに別クラスの次の空いているムーンが割り当てられます。",
          tip1="十分な数のムーンをチェックしてください。自分の番の前に希望ムーンがすべて埋まると、コーポは何も得られません。",
          tip2="全メンバーがキャラクターを Auth に登録しているか確認してください。登録済みのプレイヤーだけがアクティブメンバーとして数えられます。",
          tip3="FATリンク付きのフリートに参加して戦いましょう。それが最も重要です。",
      ))

# ---------------------------------------------------------------- Korean
build("ko", "위성 분배 방식 안내", "이 페이지에는 항상 마이닝 오피서의 현재 설정이 표시됩니다.",
      ["1. 개요", "2. 진행 순서", "3. 누가 신청할 수 있나요?", "4. 신청 방법",
       "5. 코퍼레이션 평가 방식", "6. 보너스 점수", "7. 위성 배정 방식", "8. 팁"],
      dict(
          intro="얼라이언스는 몇 달마다 위성을 다시 분배합니다. 각 코퍼레이션은 원하는 위성에 신청하고, Auth가 활동량으로 코퍼레이션을 평가하여 위성을 <strong>자동으로, 투명하게</strong> 배정합니다.",
          r64="위성은 얼라이언스가 보유하며 분배되지 않습니다.",
          tl1="마이닝 오피서가 라운드를 준비하고 엽니다.",
          tl2=f"그때부터 <strong>{V['days']}일</strong> 동안 신청을 받습니다. 마감 전까지 언제든지 신청을 변경할 수 있습니다.",
          tl3="기간이 끝나면 라운드가 자동으로 평가되고 <strong>정확히 한 번</strong> 분배됩니다.",
          tl4="신청한 모든 사람은 결과가 담긴 Auth 알림을 받습니다. 전체 순위는 라운드 페이지에서 볼 수 있습니다.",
          who="얼라이언스 소속 코퍼레이션의 <strong>CEO</strong> – 코퍼레이션당 신청 1건.",
          who_dir="<strong>디렉터</strong>도 신청할 수 있습니다. 디렉터는 Corptools로 확인하므로 캐릭터에 활성화된 Corptools 감사가 필요합니다.",
          prob=f"코퍼레이션은 얼라이언스에 최소 <strong>{V['prob']}개월</strong> 이상 소속되어 있어야 합니다(마지막 가입일 기준). 수습 기간 중인 코퍼레이션은 신청할 수 없으며, 마이닝 오피서가 예외를 허용할 수 있습니다.",
          ap1="<em>Moon Distribution → 라운드</em>를 열고 내 코퍼레이션 옆의 <em>신청</em>을 클릭합니다.",
          ap2=f"코퍼레이션이 원하는 위성을 모두 체크합니다 – 최대 <strong>{V['wishes']}</strong>개. 위성은 지역별 탭으로 나뉘어 있으며, 선택은 모든 탭에 걸쳐 적용됩니다.",
          ap3="열 제목을 클릭하면 정렬됩니다(예: 희귀도 또는 고가치 광석 비율). Shift+클릭으로 두 번째 정렬 기준을 추가할 수 있습니다.",
          ap4="저장합니다. 체크한 위성은 모두 동등하게 취급되며 우선순위는 없습니다.",
          colors="색상:",
          chips="위성 옆의 라벨은 광석과 그 비율을 보여 줍니다. <em>최고 %</em>는 해당 위성 등급에서 가장 가치 있는 광석의 비율입니다.",
          rate="라운드에 표시된 기간(보통 최근 약 6개월)의 활동을 측정합니다. 각 기준은 신청한 코퍼레이션 중 최고를 100으로 하여 0~100으로 환산되며, 가중 평균이 점수가 됩니다.",
          c_crit="기준", c_src="데이터 출처", c_w="가중치",
          src_pvp="코퍼레이션이 파괴한 함선(zKillboard)", n_fleet="함대", src_fleet="함대 참여(FAT 링크)",
          n_mem="활동 멤버", src_mem=f"메인 캐릭터가 코퍼레이션에 있고 최근 {V['act']}일 이내에 접속한 플레이어",
          n_rate="활동 비율", src_rate=f"코퍼레이션의 전체 캐릭터(EVE 기준 멤버 수) 중 최근 {V['act']}일 이내에 접속한 비율 – Auth에 등록되지 않은 캐릭터는 비활동으로 계산됩니다",
          per_member="PvP와 함대는 <strong>활동 멤버 1인당</strong>으로 계산되어, 작지만 매우 활발한 코퍼레이션도 큰 코퍼레이션과 경쟁할 수 있습니다.",
          main="모든 활동은 <strong>메인 캐릭터</strong>의 코퍼레이션에 합산됩니다. 다른 코퍼레이션의 부캐도 메인의 코퍼레이션에 합산됩니다.",
          b_moon="지난 라운드에 신청했지만 위성을 하나도 받지 못한 경우.",
          b_r32="지난 라운드에 위성은 받았지만 다음 등급은 하나도 받지 못한 경우:",
          b_manual="마이닝 오피서는 코퍼레이션에 추가 점수를 주거나 감점할 수 있으며, 그 사유는 항상 라운드 페이지에 모두에게 공개됩니다.",
          d1="신청한 모든 코퍼레이션을 총점 순으로 정렬합니다(동점이면 먼저 신청한 쪽이 우선).",
          d2="차례대로 각 코퍼레이션이 <strong>하나</strong>의 위성을 받습니다: 체크한 위성 중 아직 남아 있는 가장 좋은 위성(먼저 희귀도, 그다음 고가치 광석 비율).",
          d3=f"그다음 다시 최고 코퍼레이션부터 다음 바퀴가 시작되며, 각 코퍼레이션이 <strong>{V['maxm']}</strong>개의 위성을 받거나 원하는 위성이 모두 소진될 때까지 계속됩니다.",
          lim="코퍼레이션·라운드당 한도:", lim2="한도에 도달하면 대신 다른 등급의 다음 남은 위성이 배정됩니다.",
          tip1="위성을 충분히 체크하세요. 내 차례 전에 원하는 위성이 모두 배정되면 코퍼레이션은 아무것도 받지 못합니다.",
          tip2="모든 멤버가 Auth에 캐릭터를 등록했는지 확인하세요. 등록된 플레이어만 활동 멤버로 계산됩니다.",
          tip3="FAT 링크가 있는 함대에 참여하고 싸우세요. 그것이 가장 중요합니다.",
      ))

# ---------------------------------------------------------------- Simplified Chinese
build("zh_hans", "卫星分配说明", "本页面始终显示 Mining Officer 的当前设置。",
      ["1. 这是什么？", "2. 流程", "3. 谁可以申请？", "4. 如何申请",
       "5. 军团如何评分", "6. 加分", "7. 卫星如何分配", "8. 建议"],
      dict(
          intro="联盟每隔几个月重新分配一次卫星。各军团申请想要的卫星，Auth 根据活跃度为每个军团评分，并<strong>自动、透明地</strong>分配卫星。",
          r64="卫星由联盟保留，不参与分配。",
          tl1="Mining Officer 准备并开启一轮分配。",
          tl2=f"开启后申请期为 <strong>{V['days']} 天</strong>。截止前可以随时修改申请。",
          tl3="时间结束后，本轮会自动评分并<strong>只分配一次</strong>。",
          tl4="所有申请人都会收到包含结果的 Auth 通知。完整排名可在本轮页面查看。",
          who="联盟军团的 <strong>CEO</strong> – 每个军团一份申请。",
          who_dir="<strong>董事</strong>也可以申请；董事通过 Corptools 识别，因此角色需要有效的 Corptools 审计。",
          prob=f"你的军团必须已加入联盟至少 <strong>{V['prob']} 个月</strong>（从最近一次加入算起）。仍在考察期内的军团不能申请；Mining Officer 可以给予例外。",
          ap1="打开 <em>Moon Distribution → 轮次</em>，点击你军团旁边的<em>申请</em>。",
          ap2=f"勾选你军团想要的所有卫星 – 最多 <strong>{V['wishes']}</strong> 个。卫星按星域分在不同标签页中，选择在所有标签页中通用。",
          ap3="点击列标题即可排序（例如按稀有度或高价值矿石占比）；Shift+点击可添加第二级排序。",
          ap4="保存。所有勾选的卫星同等对待 – 没有优先顺序。",
          colors="颜色：",
          chips="卫星旁的标签显示其矿石及占比；<em>最高 %</em> 是该卫星等级中最有价值矿石的占比。",
          rate="统计本轮所示时间段内的活跃度（通常为最近约 6 个月）。每项指标以申请军团中的最高者为 100，换算为 0–100 分，加权平均即为你的得分。",
          c_crit="指标", c_src="数据来源", c_w="权重",
          src_pvp="你军团击毁的舰船（zKillboard）", n_fleet="舰队", src_fleet="舰队参与（FAT 链接）",
          n_mem="活跃成员", src_mem=f"主角色在你军团中、且在最近 {V['act']} 天内登录过的玩家",
          n_rate="活跃率", src_rate=f"你军团所有角色（EVE 成员数）中最近 {V['act']} 天内登录过的比例 – 未在 Auth 中注册的角色视为不活跃",
          per_member="PvP 和舰队按<strong>每名活跃成员</strong>计算，让规模小但非常活跃的军团也能与大军团竞争。",
          main="所有数据都计入<strong>主角色</strong>所在的军团——在其他军团的小号也计入主号的军团。",
          b_moon="如果你的军团上一轮申请了但没有得到任何卫星。",
          b_r32="如果你的军团上一轮得到了卫星，但没有得到以下等级：",
          b_manual="Mining Officer 可以给军团额外加分（或扣分）——理由始终在本轮页面上对所有人公开。",
          d1="所有申请军团按总分排序（同分时先申请者优先）。",
          d2="各军团依次获得<strong>一个</strong>卫星：在其勾选的卫星中仍空闲的最好的一个（先看稀有度，再看高价值矿石占比）。",
          d3=f"然后从最高分军团开始下一轮，直到每个军团获得 <strong>{V['maxm']}</strong> 个卫星，或其想要的卫星都已被分走。",
          lim="每个军团每轮的上限：", lim2="达到上限后，将改为分配另一等级的下一个空闲卫星。",
          tip1="勾选足够多的卫星——如果在轮到你之前你想要的卫星都被分走，你的军团将一无所获。",
          tip2="确保所有成员都已在 Auth 中注册角色——只有注册的玩家才算活跃成员。",
          tip3="参加带 FAT 链接的舰队并积极战斗——这最重要。",
      ))


TEMPLATE = """{{% extends "moondistribution/guide/_layout.html" %}}
{{# Generated guide for language "{lang}" – edit the generator or this file #}}
{{% block guide_title %}}{title}{{% endblock guide_title %}}
{{% block guide_body %}}
{body}
{{% endblock guide_body %}}
{{% block guide_footer %}}{footer}{{% endblock guide_footer %}}
"""

os.makedirs(OUT, exist_ok=True)
for lang, data in T.items():
    body = "\n".join(f'<h5 class="mt-3">{h}</h5>\n{txt}' for h, txt in data["sections"])
    with open(os.path.join(OUT, f"{lang}.html"), "w", encoding="utf-8") as f:
        f.write(TEMPLATE.format(lang=lang, title=data["title"], body=body, footer=data["footer"]))
print(sorted(T))
