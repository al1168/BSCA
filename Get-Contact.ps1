[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [int]$CenterID,

    [string]$DbPath = '\\BOWERY3\Users\Shared\Access Member 5.5.26_copy.accdb'
)

if (-not (Test-Path -LiteralPath $DbPath)) {
    throw "Database not found: $DbPath"
}

$connStr = "Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$DbPath;Persist Security Info=False;"
$conn    = New-Object System.Data.OleDb.OleDbConnection $connStr

try {
    $conn.Open()

    $cmd = $conn.CreateCommand()
    $cmd.CommandText = 'SELECT * FROM [Contacts] WHERE [Center ID] = ?'
    $null = $cmd.Parameters.Add(
        (New-Object System.Data.OleDb.OleDbParameter('@CenterID', [int]$CenterID))
    )

    $reader  = $cmd.ExecuteReader()
    $results = @()
    while ($reader.Read()) {
        $row = [ordered]@{}
        for ($i = 0; $i -lt $reader.FieldCount; $i++) {
            $row[$reader.GetName($i)] = $reader.GetValue($i)
        }
        $results += [pscustomobject]$row
    }
    $reader.Close()
}
finally {
    $conn.Close()
}

if ($results.Count -eq 0) {
    Write-Warning "No contact found with Center ID $CenterID"
} else {
    $results | Format-List 
}
