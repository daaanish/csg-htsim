# TE Demand vs Admitted Experiment

Simple 2-node, 2-path topology to test demand (d_st) and admitted (b_st) functionality

```
  src ---[path A, 200 Mbps]---> dst
  src ---[path B, 200 Mbps]---> dst
```

Two flows (one per path), each with its own b_st and sending rate.

**Scenario 1 (balanced):** b_st = 2 units on each path, rate = capacity ==> no loss.
**Scenario 2 (unbalanced):** b_st = 3 units on A, 1 unit on B. Path A rate exceeds
capacity ==> packet loss on A, path B fine.

## Usage

```bash
./run.sh
```

To iterate, edit the variables at the top of `run.sh`:

```bash
D_ST=600000000          # total demand (6 units)
B_ST_A_1=200000000      # scenario 1: b_st path A
B_ST_B_1=200000000      # scenario 1: b_st path B
RATE_A_1=200            # scenario 1: rate path A (Mbps)
RATE_B_1=200            # scenario 1: rate path B (Mbps)
B_ST_A_2=300000000      # scenario 2: b_st path A
B_ST_B_2=100000000      # scenario 2: b_st path B
RATE_A_2=300            # scenario 2: rate path A (Mbps)
RATE_B_2=100            # scenario 2: rate path B (Mbps)
```

1 unit = 100 MB. Link capacity = 200 Mbps per path.
