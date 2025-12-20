import re
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd

@dataclass
class LogEntry:
    """Represents a single log entry from htsim output"""
    timestamp: float
    type: str
    id: int
    event: str
    flow_id: int
    packet_type: str
    seqno: int
    packet_size: str
    
    def __repr__(self):
        return (f"LogEntry(t={self.timestamp:.9f}, ID={self.id}, "
                f"Ev={self.event}, Flow={self.flow_id}, "
                f"Ptype={self.packet_type}, Seq={self.seqno})")


class HTSimParser:
    """Parser for htsim network simulator output logs"""
    
    # Regex pattern to parse log lines
    PATTERN = re.compile(
        r'^(?P<timestamp>[\d.]+)\s+'
        r'Type\s+(?P<type>\w+)\s+'
        r'ID\s+(?P<id>\d+)\s+'
        r'Ev\s+(?P<event>\w+)\s+'
        r'FlowID\s+(?P<flow_id>\d+)\s+'
        r'Ptype\s+(?P<packet_type>\w+)\s+'
        r'Seqno\s+(?P<seqno>\d+)\s+'
        r'Psize\s+(?P<packet_size>\w+)'
    )
    
    def __init__(self):
        self.entries: List[LogEntry] = []
    
    def parse_line(self, line: str) -> Optional[LogEntry]:
        """Parse a single log line into a LogEntry object"""
        line = line.strip()
        if not line:
            return None
            
        match = self.PATTERN.match(line)
        if not match:
            return None
        
        return LogEntry(
            timestamp=float(match.group('timestamp')),
            type=match.group('type'),
            id=int(match.group('id')),
            event=match.group('event'),
            flow_id=int(match.group('flow_id')),
            packet_type=match.group('packet_type'),
            seqno=int(match.group('seqno')),
            packet_size=match.group('packet_size')
        )
    
    def parse_file(self, filename: str) -> List[LogEntry]:
        """Parse an entire log file"""
        self.entries = []
        with open(filename, 'r') as f:
            for line in f:
                entry = self.parse_line(line)
                if entry:
                    self.entries.append(entry)
        return self.entries
    
    def parse_string(self, log_text: str) -> List[LogEntry]:
        """Parse log text from a string"""
        self.entries = []
        for line in log_text.split('\n'):
            entry = self.parse_line(line)
            if entry:
                self.entries.append(entry)
        return self.entries
    
    def to_dataframe(self) -> pd.DataFrame:
        """Convert parsed entries to a pandas DataFrame"""
        if not self.entries:
            return pd.DataFrame()
        
        data = {
            'timestamp': [e.timestamp for e in self.entries],
            'type': [e.type for e in self.entries],
            'id': [e.id for e in self.entries],
            'event': [e.event for e in self.entries],
            'flow_id': [e.flow_id for e in self.entries],
            'packet_type': [e.packet_type for e in self.entries],
            'seqno': [e.seqno for e in self.entries],
            'packet_size': [e.packet_size for e in self.entries]
        }
        return pd.DataFrame(data)
    
    def filter_by_event(self, event: str) -> List[LogEntry]:
        """Filter entries by event type (e.g., 'DEPART', 'ARRIVE')"""
        return [e for e in self.entries if e.event == event]
    
    def filter_by_flow(self, flow_id: int) -> List[LogEntry]:
        """Filter entries by flow ID"""
        return [e for e in self.entries if e.flow_id == flow_id]
    
    def filter_by_node(self, node_id: int) -> List[LogEntry]:
        """Filter entries by node ID"""
        return [e for e in self.entries if e.id == node_id]
    
    def get_summary(self) -> dict:
        """Get summary statistics of parsed logs"""
        if not self.entries:
            return {}
        
        df = self.to_dataframe()
        return {
            'total_entries': len(self.entries),
            'unique_flows': df['flow_id'].nunique(),
            'unique_nodes': df['id'].nunique(),
            'events': df['event'].value_counts().to_dict(),
            'packet_types': df['packet_type'].value_counts().to_dict(),
            'time_span': (df['timestamp'].max() - df['timestamp'].min()),
            'start_time': df['timestamp'].min(),
            'end_time': df['timestamp'].max()
        }
        
        
if __name__ == "__main__":
    # Create parser and parse the log
    parser = HTSimParser()
    entries = parser.parse_file('newcmdcheck.txt')
    
    print("=== Parsed Entries ===")
    for entry in entries[:5]:  # Show first 5
        print(entry)
    
    print(f"\nTotal entries parsed: {len(entries)}")
    
    # Get summary
    print("\n=== Summary ===")
    summary = parser.get_summary()
    for key, value in summary.items():
        print(f"{key}: {value}")
    
    # Convert to DataFrame
    print("\n=== DataFrame ===")
    df = parser.to_dataframe()
    print(df.head())
    
    # Filter examples
    print("\n=== Filter by Flow ID 253 ===")
    flow_253 = parser.filter_by_flow(253)
    for entry in flow_253:
        print(entry)
    
    # --- New: pandas exploration ---
    print("\n=== Column Names ===")
    print(df.columns.tolist())
    
    print("\n=== Unique Values per Column (first 10) ===")
    for col in df.columns:
        unique_vals = df[col].unique()
        print(f"{col}: {unique_vals[:10]}{'...' if len(unique_vals) > 10 else ''}")
    
    print("\n=== Value Counts for Categorical Columns ===")
    for cat_col in ['type', 'event', 'packet_type']:
        if cat_col in df.columns:
            print(f"\n{cat_col} counts:")
            print(df[cat_col].value_counts())
    
    print("\n=== Numeric Summary ===")
    print(df.describe())
    
    print("\n=== Crosstab: Type vs Event ===")
    print(pd.crosstab(df['type'], df['event']))
    
    print("\n=== Random Sample Rows ===")
    print(df.sample(min(5, len(df))))
