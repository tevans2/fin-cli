package styles

import "github.com/charmbracelet/lipgloss"

var (
	Title = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("81"))
	Muted = lipgloss.NewStyle().Foreground(lipgloss.Color("244"))
	Dim   = lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
	Sel   = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("231")).Background(lipgloss.Color("57"))
	Out   = lipgloss.NewStyle().Foreground(lipgloss.Color("203"))
	In    = lipgloss.NewStyle().Foreground(lipgloss.Color("120"))
	Ok    = lipgloss.NewStyle().Foreground(lipgloss.Color("120"))
	Warn  = lipgloss.NewStyle().Foreground(lipgloss.Color("214"))
	Key   = lipgloss.NewStyle().Foreground(lipgloss.Color("111"))
	Help  = lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
	Pane  = lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(lipgloss.Color("240"))
)
