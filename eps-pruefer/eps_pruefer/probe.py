"""PostScript-Prolog, der in Ghostscript vor der EPS-Datei ausgeführt wird.

Der Prolog ersetzt alle malenden Operatoren (fill, stroke, show, image, ...)
durch Prozeduren, die vor dem eigentlichen Malen den aktuellen Grafikzustand
protokollieren: Farbraum, Farbwerte, Überdrucken, Deckkraft, Ausdehnung und
bei Bildern die effektive Auflösung. Jede Zeile beginnt mit ``@@EPS|`` und
wird vom Analyzer in Python ausgewertet.

Die EPS-Daten werden über stdin hinter dem Prolog eingespeist und durch einen
SubFileDecode-Filter bis zur Endemarke gelesen. So braucht Ghostscript keinen
Dateizugriff (SAFER bleibt aktiv, keine Probleme mit Umlauten in Pfaden).
"""

EOD_MARKER = b"@@EPSPROBE-EOD-7f3a9c41@@"

# Verschiebung des EPS-Koordinatensystems auf der (sehr großen) Seite, damit
# auch negative Koordinaten nicht vom Seitenrand beschnitten werden.
PAGE_POINTS = 40000
OFFSET_POINTS = 20000

PROLOG = r"""%!PS
% ---------------------------------------------------------------------------
% EPS-Pruefer Probe
% ---------------------------------------------------------------------------
% Prüfzustand liegt im globalen VM, damit ein save/restore in der EPS
% (z. B. bei Illustrator) Zähler und "erstes Objekt" nicht zurücksetzt.
currentglobal true setglobal
/@P 40 dict def
@P begin
  /depth 0 def
  /first true def
  /npaint 0 def
  /nemit 0 def
  /nimg 0 def
  /maxemit 3000 def
  /maximg 5000 def
  /fonts 100 dict def
end
setglobal
% Zwischenwerte (lokaler VM, dürfen Matrizen u. ä. aufnehmen)
/@T 30 dict def
/@epsm matrix def
/@epsinv matrix def

/@sep { (|) print } bind def
/@num { 1000 mul round 1000 div =only } bind def
/@nl { (\n) print } bind def

/@amin { dup 0 get exch { 2 copy gt { exch } if pop } forall } bind def
/@amax { dup 0 get exch { 2 copy lt { exch } if pop } forall } bind def

/@falpha {
  /.currentfillconstantalpha where { pop .currentfillconstantalpha } { 1 } ifelse
} bind def
/@salpha {
  /.currentstrokeconstantalpha where { pop .currentstrokeconstantalpha } { 1 } ifelse
} bind def

% Basis-Farbraum eines Indexed-Farbraums ausgeben
/@basename {
  dup type /nametype eq { =only } {
    dup 0 get dup =only
    /ICCBased eq { (/) print 1 get /N get =only } { pop } ifelse
  } ifelse
} bind def

% Farbraum ausgeben als  Familie|Detail
/@csof {
  dup type /nametype eq { =only @sep } {
    dup 0 get dup =only @sep
    dup /ICCBased eq { pop 1 get /N get =only } {
    dup /Indexed eq { pop 1 get //@basename exec } {
    dup /Separation eq { pop 1 get =only } {
    dup /DeviceN eq { pop 1 get ==only } {
      pop pop
    } ifelse } ifelse } ifelse } ifelse
  } ifelse
} bind def

% aktuellen Farbraum (inkl. Verlaufsmuster) und Farbwerte ausgeben
/@curcolor {
  currentcolorspace dup 0 get /Pattern eq {
    pop
    mark currentcolor counttomark array astore exch pop
    dup length 0 gt { dup length 1 sub get } { pop null } ifelse
    dup type /dicttype eq {
      dup /Shading known {
        /Shading get /ColorSpace get //@csof exec @sep ([]) print
      } { pop (Pattern|tiling|[]) print } ifelse
    } { pop (Pattern||[]) print } ifelse
  } {
    //@csof exec @sep
    mark currentcolor counttomark array astore exch pop ==only
  } ifelse
} bind def

% Ausdehnung des aktuellen Pfads im EPS-Koordinatensystem
/@pathbox {
  gsave //@epsm setmatrix
  { flattenpath pathbbox } stopped
  { (-) print } { 4 array astore { @num ( ) print } forall } ifelse
  grestore
} bind def

% Ausdehnung des aktuellen Beschneidungspfads im EPS-Koordinatensystem
/@clipbox {
  gsave //@epsm setmatrix
  { clippath flattenpath pathbbox } stopped
  { (-) print } { 4 array astore { @num ( ) print } forall } ifelse
  grestore
} bind def

/@inc { //@P /depth 2 copy get 1 add put } bind def
/@dec { //@P /depth 2 copy get 1 sub put } bind def

% gemeinsamer Kopf jeder Mal-Zeile; setzt nested/isfirst in @P
/@head { % (op) (KIND) ->
  //@P begin
    (@@EPS|) print print @sep print @sep
    /nested depth 0 gt def
    /isfirst nested not first and def
    isfirst { /first false def } if
    nested not { /npaint npaint 1 add def } if
    nested { (1) } { (0) } ifelse print @sep
    isfirst { (1) } { (0) } ifelse print @sep
  end
} bind def

% Soll eine Vektor-Malung ausgegeben werden? (Obergrenze gegen riesige Logs)
/@wanted { % -> bool
  //@P begin
    depth 0 eq first and
    currentoverprint or
    //@falpha exec 1 lt or
    //@salpha exec 1 lt or
    currentcolorspace 0 get /DeviceCMYK ne or
    nemit maxemit lt and
    dup { /nemit nemit 1 add def } {
      depth 0 eq { /npaint npaint 1 add def /first false def } if
    } ifelse
  end
} bind def

% Vektor-Malung protokollieren: (op) stroke? usepath? ->
/@rec {
  //@wanted exec {
    3 -1 roll (PAINT) //@head exec
    //@curcolor exec @sep
    currentoverprint =only @sep
    exch { //@salpha exec } { //@falpha exec } ifelse @num @sep
    { //@pathbox exec } { (-) print } ifelse @sep
    //@clipbox exec
    @nl
  } { pop pop pop } ifelse
} bind def

% Bild protokollieren: w h matrix (op) csspec ->
%   csspec = /cur (aktueller Farbraum) oder Name eines Geraeteraums
/@recimg {
  //@T begin
    /ics exch def /iop exch def /im exch def /ih exch def /iw exch def
  end
  //@P /nimg get //@P /maximg get lt {
    //@P /nimg 2 copy get 1 add put
    //@T /iop get (IMAGE) //@head exec
    //@T /ics get /cur eq { //@curcolor exec } {
      //@T /ics get //@csof exec @sep ([]) print
    } ifelse @sep
    currentoverprint =only @sep
    //@falpha exec @num @sep
    //@T begin
    mark {
      /M im matrix invertmatrix matrix currentmatrix matrix concatmatrix
         //@epsinv matrix concatmatrix def
      /xs [ 0 0 M transform pop  iw 0 M transform pop
            0 ih M transform pop  iw ih M transform pop ] def
      /ys [ 0 0 M transform exch pop  iw 0 M transform exch pop
            0 ih M transform exch pop  iw ih M transform exch pop ] def
      xs //@amin exec @num ( ) print ys //@amin exec @num ( ) print
      xs //@amax exec @num ( ) print ys //@amax exec @num ( ) print
      @sep //@clipbox exec @sep
      iw =only @sep ih =only @sep
      iw 0 M dtransform dup mul exch dup mul add sqrt /lx exch def
      0 ih M dtransform dup mul exch dup mul add sqrt /ly exch def
      lx 0 gt { iw 72 mul lx div } { 0 } ifelse @num @sep
      ly 0 gt { ih 72 mul ly div } { 0 } ifelse @num
    } stopped { (-|-|0|0|0|0) print } if
    cleartomark
    end
    @nl
  } if
} bind def

% pdfmark: Transparenz-Angaben (Distiller-Erweiterung) erkennen
/@pdfmark {
  counttomark 0 gt {
    dup /SetTransparency eq {
      (@@EPS|TRANSP|) print
      //@P /first get { (1) } { (0) } ifelse print @sep
      counttomark 1 sub -1 1 { index ==only ( ) print } for
      @nl
    } if
  } if
  cleartomark
} bind def

/@rect4 { % x y w h -> Pfad
  //@T begin /rh exch def /rw exch def end
  moveto //@T /rw get 0 rlineto 0 //@T /rh get rlineto
  //@T /rw get neg 0 rlineto closepath
} bind def

/@rectpath { % operanden von rectfill -> baut Pfad, laesst Operanden liegen
  dup type dup /arraytype eq exch /packedarraytype eq or {
    dup aload length 4 idiv { //@rect4 exec } repeat
  } {
    dup type /stringtype eq { } { 4 copy //@rect4 exec } ifelse
  } ifelse
} bind def

% Schrift wird benutzt: melden, wenn sie nicht von der EPS selbst definiert wurde
/@fontuse { % key -> key
  dup //@P /fonts get exch known not {
    dup //@P /fonts get exch true put
    (@@EPS|FONT|) print dup =only @nl
  } if
} bind def
/@fontdef { % key -> key
  dup //@P /fonts get exch true put
} bind def

% ---------------------------------------------------------------------------
% Operatoren ersetzen (in userdict, dadurch greift auch "bind" der EPS nicht)
% ---------------------------------------------------------------------------
% Originale sichern; in Ghostscript sind manche davon Prozeduren, daher
% werden sie immer per "get exec" aufgerufen.
/@O 40 dict def
[ /fill /eofill /stroke /rectfill /rectstroke /shfill /show /ashow /widthshow /awidthshow /kshow /xshow /yshow /xyshow /glyphshow /image /imagemask /colorimage /definefont /findfont /selectfont /defineresource /findresource ]
{ dup load @O 3 1 roll put } forall

userdict begin
/fill   { (fill) false true //@rec exec   //@inc exec //@O /fill get exec   //@dec exec } def
/eofill { (eofill) false true //@rec exec //@inc exec //@O /eofill get exec //@dec exec } def
/stroke { (stroke) true true //@rec exec  //@inc exec //@O /stroke get exec //@dec exec } def
/rectfill {
  gsave newpath //@rectpath exec (rectfill) false true //@rec exec grestore
  //@inc exec //@O /rectfill get exec //@dec exec
} def
/rectstroke { (rectstroke) true false //@rec exec //@inc exec //@O /rectstroke get exec //@dec exec } def
/shfill {
  (shfill) (PAINT) //@head exec
  dup /ColorSpace get //@csof exec @sep ([]) print @sep
  currentoverprint =only @sep //@falpha exec @num @sep
  //@clipbox exec @sep //@clipbox exec @nl
  //@inc exec //@O /shfill get exec //@dec exec
} def
/show        { (show) false false //@rec exec        //@inc exec //@O /show get exec        //@dec exec } def
/ashow       { (ashow) false false //@rec exec       //@inc exec //@O /ashow get exec       //@dec exec } def
/widthshow   { (widthshow) false false //@rec exec   //@inc exec //@O /widthshow get exec   //@dec exec } def
/awidthshow  { (awidthshow) false false //@rec exec  //@inc exec //@O /awidthshow get exec  //@dec exec } def
/kshow       { (kshow) false false //@rec exec       //@inc exec //@O /kshow get exec       //@dec exec } def
/xshow       { (xshow) false false //@rec exec       //@inc exec //@O /xshow get exec       //@dec exec } def
/yshow       { (yshow) false false //@rec exec       //@inc exec //@O /yshow get exec       //@dec exec } def
/xyshow      { (xyshow) false false //@rec exec      //@inc exec //@O /xyshow get exec      //@dec exec } def
/glyphshow   { (glyphshow) false false //@rec exec   //@inc exec //@O /glyphshow get exec   //@dec exec } def
/image {
  dup type /dicttype eq {
    dup dup /DataDict known { /DataDict get } if
    dup /Width get exch dup /Height get exch /ImageMatrix get
    (image) /cur //@recimg exec
  } {
    4 index 4 index 3 index (image) /DeviceGray //@recimg exec
  } ifelse
  //@inc exec //@O /image get exec //@dec exec
} def
/imagemask {
  dup type /dicttype eq {
    dup /Width get 1 index /Height get 2 index /ImageMatrix get
  } {
    4 index 4 index 3 index
  } ifelse
  (imagemask) /cur //@recimg exec
  //@inc exec //@O /imagemask get exec //@dec exec
} def
/colorimage {
  //@T begin /cn exch def /cmu exch def /cns cmu { cn } { 1 } ifelse def end
  //@T /cns get 3 add index
  //@T /cns get 3 add index
  //@T /cns get 2 add index
  (colorimage)
  //@T /cn get dup 4 eq { pop /DeviceCMYK } { 3 eq { /DeviceRGB } { /DeviceGray } ifelse } ifelse
  //@recimg exec
  //@T /cmu get //@T /cn get
  //@inc exec //@O /colorimage get exec //@dec exec
} def
/pdfmark { //@pdfmark exec } def
/definefont { 1 index //@fontdef exec pop //@O /definefont get exec } def
/findfont { //@fontuse exec //@O /findfont get exec } def
/selectfont { 1 index //@fontuse exec pop //@O /selectfont get exec } def
/defineresource {
  dup /Font eq { 2 index //@fontdef exec pop } if //@O /defineresource get exec
} def
/findresource {
  dup /Font eq { 1 index //@fontuse exec pop } if //@O /findresource get exec
} def
/showpage { } def
/copypage { } def
/erasepage { } def
/quit { } def
/setpagedevice { pop } def
end

(@@EPS|START|) print revision =only @nl

% EPS-Koordinatensystem festlegen
%%OFFSET%% %%OFFSET%% translate
@epsm currentmatrix pop
@epsm @epsinv invertmatrix pop

% Standard-Umgebung fuer eingebettetes EPS
0 setgray 0 setlinecap 1 setlinewidth 0 setlinejoin 10 setmiterlimit
[] 0 setdash newpath false setoverprint false setstrokeadjust

% Die EPS-Daten folgen im Eingabestrom direkt hinter dem Aufruf von @runeps
/@runeps {
  /@osc count def
  /@dsc countdictstack def
  /@epsdata currentfile 0 (%%EOD%%) /SubFileDecode filter def
  { @epsdata cvx exec } stopped {
    (@@EPS|ERROR|) print
    $error /errorname get =only @sep
    $error /command get dup type /stringtype eq { print } { ==only } ifelse @nl
    @epsdata flushfile
  } if
} bind def
@runeps
"""

EPILOG = r"""
count @osc sub dup 0 gt { { pop } repeat } { pop } ifelse
countdictstack @dsc sub dup 0 gt { { end } repeat } { pop } ifelse
(@@EPS|END|) print @P /npaint get =only @sep @P /nimg get =only @sep @P /nemit get =only @nl
"""


def build_job(eps_data: bytes) -> bytes:
    """Setzt Prolog, EPS-Daten und Epilog zu einem Ghostscript-Job zusammen."""
    prolog = (
        PROLOG.replace("%%OFFSET%%", str(OFFSET_POINTS))
        .replace("%%EOD%%", EOD_MARKER.decode("ascii"))
        .encode("latin-1")
    )
    if EOD_MARKER in eps_data:
        raise ValueError("EPS-Daten enthalten die interne Endemarke")
    return (
        prolog
        + eps_data
        + b"\n"
        + EOD_MARKER
        + b"\n"
        + EPILOG.encode("latin-1")
    )
