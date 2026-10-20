REFERENCE ONLY
==============

This file preserves the earlier Power Query transformation for audit and
comparison. It is not the current operating entry point.

The current Python pipeline automatically combines:
- data/core/Newlands_historical_core_through_2025.csv
- supported 2026+ survey exports placed in data/future

Files imported from data/future are observed survey data. The current scenario
pipeline starts projections in the year after the latest imported survey year;
the folder name does not cause those records to be labelled as projected.

Run `python newlands_integrated_pipeline.py` from the project folder. See the
project README and docs/OPERATING_GUIDE.md for current instructions.

Legacy Power Query follows:

let
    // Load your main CSV
    Source =
        Csv.Document(File.Contents("<historical analysis CSV path omitted>"),[Delimiter=",", Columns=44, Encoding=1252, QuoteStyle=QuoteStyle.None]),
    // Convert to table with headers
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),

    // Ensure numeric columns are typed correctly
    ChangedType =
        Table.TransformColumnTypes(
            PromotedHeaders,
            {
                {"satisfaction_income", Int64.Type},
                {"confident_in_finding_a_new_job", Int64.Type},
                {"confident_water_safety", Int64.Type},
                {"optimal_use_of_land", Int64.Type},
                {"personal_mental_health", Int64.Type}
            },
            "en-NZ"
        ),
    #"Filtered Rows1" = Table.SelectRows(ChangedType, each true),
    // Convert empty strings to nulls in all question columns
    ReplaceEmptyWithNull =
        Table.ReplaceValue(
            #"Filtered Rows1",
            "",
            null,
            Replacer.ReplaceValue,
            {
                "satisfaction_income",
                "confident_in_finding_a_new_job",
                "confident_water_safety",
                "optimal_use_of_land",
                "personal_mental_health",
                "language",
                "belonging",
                "cultural_activities",
                "te_reo",
                "cultural_knowledge",
                "trust_nz_government",
                "trust_local_council",
                "safety",
                "be_yourself_in_nz",
                "be_yourself_in_newlands",
                "discrimination",
                "loneliness",
                "support_in_crisis",
                "level_of_control",
                "volunteering_time",
                "job_satisfaction",
                "work_life_balance",
                "leisure_time",
                "life_satisfaction",
                "meaning_and_purpose",
                "family_wellbeing",
                "access_to_natural_environment",
                "basic_life_skills"
            }
        ),

    // Load your lookup table
    AvgTable = average_questions,

    // Build lookup record
    AvgLookup =
        Record.FromTable(
            Table.RenameColumns(
                Table.TransformColumns(
                    AvgTable,
                    {{"Question", Text.Lower}}
                ),
                {{"Question", "Name"}, {"AvgScore_3yr", "Value"}}
            )
        ),

    // Backfill the 5 core columns AFTER empty->null conversion
    FilledWithAverages =
        Table.TransformColumns(
            ReplaceEmptyWithNull,
            {
                {"satisfaction_income", each if _ = null then AvgLookup[satisfaction_income] else _},
                {"confident_in_finding_a_new_job", each if _ = null then AvgLookup[confident_in_finding_a_new_job] else _},
                {"confident_water_safety", each if _ = null then AvgLookup[confident_water_safety] else _},
                {"optimal_use_of_land", each if _ = null then AvgLookup[optimal_use_of_land] else _},
                {"personal_mental_health", each if _ = null then AvgLookup[personal_mental_health] else _}
            }
        ),

    // Count remaining nulls across all question columns AFTER backfill
    AddedCustom =
        Table.AddColumn(
            FilledWithAverages,
            "Number_null_values",
            each
                let
                    QuestionCols = {
                        "satisfaction_income",
                        "confident_in_finding_a_new_job",
                        "confident_water_safety",
                        "optimal_use_of_land",
                        "personal_mental_health",
                        "language",
                        "belonging",
                        "cultural_activities",
                        "te_reo",
                        "cultural_knowledge",
                        "trust_nz_government",
                        "trust_local_council",
                        "safety",
                        "be_yourself_in_nz",
                        "be_yourself_in_newlands",
                        "discrimination",
                        "loneliness",
                        "support_in_crisis",
                        "level_of_control",
                        "volunteering_time",
                        "job_satisfaction",
                        "work_life_balance",
                        "leisure_time",
                        "life_satisfaction",
                        "meaning_and_purpose",
                        "family_wellbeing",
                        "access_to_natural_environment",
                        "basic_life_skills"
                    },

                    ExistingCols = List.Intersect({ QuestionCols, Record.FieldNames(_) }),
                    Values = Record.ToList(Record.SelectFields(_, ExistingCols)),
                    NullCount = List.Count(List.Select(Values, each _ = null))
                in
                    NullCount
        ),
    // Keep only rows with 6 or fewer remaining nulls
    FilteredRows =
        Table.SelectRows(AddedCustom, each [Number_null_values] <= 6),
    #"Filtered Rows" = Table.SelectRows(FilteredRows, each true),
    #"Removed Columns" = Table.RemoveColumns(#"Filtered Rows",{"Number_null_values"}),
    #"Changed Type" = Table.TransformColumnTypes(#"Removed Columns",{{"date", type date}}),
    #"Added Index" = Table.AddIndexColumn(#"Changed Type", "Index", 1, 1, Int64.Type),
    #"Renamed Columns" = Table.RenameColumns(#"Added Index",{{"Index", "Responder_ID"}}),
    #"Reordered Columns" = Table.ReorderColumns(#"Renamed Columns",{"Responder_ID", "date", "age_range", "gender", "language", "belonging", "cultural_activities", "te_reo", "cultural_knowledge", "trust_nz_government", "trust_local_council", "trust_nz_police", "safety", "discrimination", "loneliness", "independence", "support_in_crisis", "level_of_control", "volunteering_time", "paid_working_hours", "job_satisfaction", "work_life_balance", "leisure_time", "be_yourself_in_nz", "be_yourself_in_newlands", "life_satisfaction", "meaning_and_purpose", "family_wellbeing", "access_to_natural_environment", "work_travel_time", "basic_life_skills", "newlands_resident", "home_disaster_ready", "neighbourhood_support_group", "out_of_newlands_during_day", "place_out_of_newlands_disaster_ready", "satisfaction_income", "confident_in_finding_a_new_job", "confident_water_safety", "optimal_use_of_land", "personal_mental_health", "vote_local_elections_2019", "vote_general_election_2020", "voted_local_elections_2022", "voted_general_elections_2023"}),
    #"Unpivoted Other Columns" = Table.UnpivotOtherColumns(#"Reordered Columns", {"Responder_ID", "date", "age_range", "gender"}, "Attribute", "Value"),
    #"Renamed Columns1" = Table.RenameColumns(#"Unpivoted Other Columns",{{"Attribute", "Question"}, {"Value", "Score"}}),
    #"Changed Type1" = Table.TransformColumnTypes(#"Renamed Columns1",{{"Score", Int64.Type}}),
    #"Added Reverse_override" = Table.AddColumn(
    #"Changed Type1",
    "Reverse_override",
    each if [Question] = "loneliness" then 1
         else if [Question] = "discrimination" then 1
         else 0
),
#"Added Paid_working_hours_score" =
    Table.AddColumn(
        #"Added Reverse_override",
        "Paid_working_hours_score",
        each 
            if [Question] = "paid_working_hours" then
                 let
                    h = [Score]
                in
                    if h = null then null
                    else if h < 10 then 20
                    else if h < 20 then 40
                    else if h < 30 then 70
                    else if h <= 40 then 100
                    else if h <= 50 then 80
                    else if h <= 60 then 50
                    else 20
        else
            null
    ),
    #"Added work_travel_time_score" =
    Table.AddColumn(
        #"Added Paid_working_hours_score",
        "work_travel_time_score",
        each 
            if [Question] = "work_travel_time" then
                 let
                    t = [Score]
                in
                    if t = null then null
                    else if t < 5 then 100
                    else if t < 10 then 95
                    else if t < 20 then 90
                    else if t < 25 then 85
                    else if t <= 30 then 80
                    else if t <= 40 then 60
                    else if t <= 50 then 40
                    else if t <= 60 then 20
                    else 10
            else
                null
    ),

    #"Added leisure_time_score" =
    Table.AddColumn(
        #"Added work_travel_time_score",
        "leisure_time_score",
        each 
                 if [Question] = "leisure_time" then
                let
                    h = [Score]
                in
                    if h = null then null
                    else if h < 5 then 10
                    else if h < 10 then 20
                    else if h < 20 then 30
                    else if h < 30 then 60
                    else if h = 30 then 80
                    else if h < 40 then 90
                    else if h < 50 then 95
                    else if h <= 60 then 100
                    else 90
            else
                null
    ),
    #"Added BinaryScore100" = 
    Table.AddColumn(
   #"Added leisure_time_score",
   "BinaryScore100",
   each
    if  [Question] = "newlands_resident" or
        [Question] = "vote_local_elections_2019" or
        [Question] = "vote_general_election_2020" or
        [Question] = "voted_local_elections_2022" or
        [Question] = "voted_general_elections_2023" or
        [Question] = "home_disaster_ready" or
        [Question] = "neighbourhood_support_group" or
        [Question] = "out_of_newlands_during_day" or
        [Question] = "place_out_of_newlands_disaster_ready"
    then
        if [Score] = null then null
        else if [Score] = 1 then 100
        else 0
    else
        [Score]
),
    #"Added CleanScore" =
    Table.AddColumn(
        #"Added BinaryScore100",
        "CleanScore",
    each
            if [Question] = "paid_working_hours" then [Paid_working_hours_score]
            else if [Question] = "work_travel_time" then [work_travel_time_score]
            else if [Question] = "leisure_time" then [leisure_time_score]
            else if [BinaryScore100] <> null then
                if [Reverse_override] = 1 then 100 - [BinaryScore100] else [BinaryScore100]
            else
                null
    ),
    #"Changed Type2" = Table.TransformColumnTypes(#"Added CleanScore",{{"CleanScore", Int64.Type}}),
    #"Removed Columns1" = Table.RemoveColumns(#"Changed Type2",{"Paid_working_hours_score", "work_travel_time_score", "leisure_time_score", "BinaryScore100", "Reverse_override"})
in
    #"Removed Columns1"

