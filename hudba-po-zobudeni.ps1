# ---------------------------------------------------------------------------
# Zaregistruje naplanovanu ulohu "Hudba po zobudeni".
#
# SPUSTIT NA TOM NOTEBOOKU, KDE BEZI PREHRAVAC (ten s 192.168.1.50).
#
# Preco naplanovana uloha a nie autostart cez Run kluc: Run sa spusti IBA pri
# prihlaseni. Zobudenie zo spanku prihlasenie nie je - relacia uz existuje,
# takze Windows pri nom nespusta nic. Ked teda appka pred uspanim nebezala,
# po zobudeni sa sama neobjavi, aj keby zamok obrazovky nebol.
#
# Naopak GUI appka spustena z ulohy prezije aj uzamknutu plochu: relacia zije,
# audio zariadenie sa da otvorit a hudba hra aj ked je na obrazovke prihlasovacia
# tabulka. Preto je toto odpoved aj na "nech tabulka ostane, ale nech hudba hra".
#
# Uloha sa sklada z XML a nie z cmdletov New-ScheduledTaskTrigger. Spustac na
# udalost sa cez cmdlety zalozit neda - New-CimInstance MSFT_TaskEventTrigger
# vyrobi objekt, ktory Register-ScheduledTask odmietne (nesedi PSTypeName), a
# schtasks si zase lame zuby na uvodzovkach v ceste. XML je jedina cesta, ktora
# zvladne oboje naraz.
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'

$uloha     = 'Hudba po zobudeni'
$priecinok = Split-Path -Parent $MyInvocation.MyCommand.Path
$akcia     = Join-Path $priecinok 'spusti-ak-nebezi.cmd'
$ja        = "$env:USERDOMAIN\$env:USERNAME"

Write-Host ''
Write-Host '    ============================================'
Write-Host "      Naplanovana uloha: $uloha"
Write-Host '    ============================================'
Write-Host ''

if (-not (Test-Path $akcia)) {
    Write-Host "    CHYBA: nenasiel som $akcia"
    Write-Host '    Skopiruj cely priecinok hudba-lan, nie len tento subor.'
    return
}

if (Get-ScheduledTask -TaskName $uloha -ErrorAction SilentlyContinue) {
    Write-Host '    Uloha uz existuje - prepisujem ju.'
    Unregister-ScheduledTask -TaskName $uloha -Confirm:$false
}

# Udalost 1 od Power-Troubleshooter v systemovom logu = navrat zo spanku.
# Vnutorne XML dotazu musi byt v Subscription escapovane, preto tie &lt; &gt;.
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Spusti Metal Music Player po zobudeni zo spanku a po prihlaseni, ak este nebezi.</Description>
  </RegistrationInfo>
  <Triggers>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
    </EventTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$ja</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$ja</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>/c "$akcia"</Arguments>
      <WorkingDirectory>$priecinok</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask -TaskName $uloha -Xml $xml | Out-Null
Write-Host '    Zalozena.'

Write-Host ''
Write-Host '    ============================================'
Write-Host '      Kontrola'
Write-Host '    ============================================'
$t = Get-ScheduledTask -TaskName $uloha
Write-Host ("    Stav:      " + $t.State)
Write-Host ("    Spusta:    " + $t.Actions[0].Execute + ' ' + $t.Actions[0].Arguments)
Write-Host ("    Bezi ako:  " + $t.Principal.UserId + ' (' + $t.Principal.LogonType + ')')
Write-Host ("    Spustacov: " + $t.Triggers.Count)
foreach ($tr in $t.Triggers) {
    $popis = switch ($tr.CimClass.CimClassName) {
        'MSFT_TaskEventTrigger' { 'zobudenie zo spanku' }
        'MSFT_TaskLogonTrigger' { 'prihlasenie' }
        default                 { $tr.CimClass.CimClassName }
    }
    Write-Host ("               - " + $popis)
}
Write-Host ''
Write-Host '    Skuska bez uspavania:  schtasks /run /tn "Hudba po zobudeni"'
Write-Host '    Zrusenie:              schtasks /delete /tn "Hudba po zobudeni" /f'
Write-Host ''
