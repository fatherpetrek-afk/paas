#ifndef CONSTANTS_H
#define CONSTANTS_H
#include <iostream>
#include <string>
using namespace std;

/**
 * Semester names.
 */
enum Semester { Fall, Winter, Spring, Summer };

/**
 * Prints a semester as a string.
 * @param semester The semester to print
 */
inline string semesterToString(const Semester &semester) {
    switch (semester) {
        case Fall:   return "Fall";
        case Winter: return "Winter";
        case Spring: return "Spring";
        case Summer: return "Summer";
        default: return "Unreachable: No such enum type";
    }
}

/**
 * Possible grades to be recorded in any courses.
 */
enum Grades { ONGOING, A_PLUS, A, A_MINUS, B_PLUS, B, B_MINUS, C_PLUS, C, C_MINUS, D, P, F };

/**
 * Number of grades in the Grades enumeration.
 */
const int NUM_POSSIBLE_GRADES = 13;

/**
 * Converts a grade to its ordinal.
 * @param grade The grade to convert
 * @return The ordinal the grade represents.
 */
inline double gradeToOrdinal(const Grades &grade) {
    switch (grade) {
        case A_PLUS:  return 4.3;
        case A:       return 4.0;
        case A_MINUS: return 3.7;
        case B_PLUS:  return 3.3;
        case B:       return 3.0;
        case B_MINUS: return 2.7;
        case C_PLUS:  return 2.3;
        case C:       return 2.0;
        case C_MINUS: return 1.7;
        case D:       return 1.0;
        default:      return 0.0;
    }
}

/**
 * Prints a grade as a string.
 * @param grade The grade to print
 */
inline string gradeToString(const Grades &grade) {
    switch (grade) {
        case ONGOING: return "Ongoing";
        case A_PLUS:  return "A+";
        case A:       return "A";
        case A_MINUS: return "A-";
        case B_PLUS:  return "B+";
        case B:       return "B";
        case B_MINUS: return "B-";
        case C_PLUS:  return "C+";
        case C:       return "C";
        case C_MINUS: return "C-";
        case D:       return "D";
        case P:       return "P";
        case F:       return "F";
        default:      return "Unreachable: No such enum type";
    }
}

/**
 * Types of students.
 */
enum StudentType { LOCAL, MAINLAND, INTERNATIONAL };

/**
 * Converts a student type to a string.
 * @param type The type of student
 * @return The string representation of the student type.
 */
inline string studentTypeToString(const StudentType &type) {
    switch (type) {
        case LOCAL:
            return "local";
        case MAINLAND:
            return "mainland";
        case INTERNATIONAL:
            return "international";
        default:
            return "Unreachable: No such enum type";
    }
}

/**
 * Regions a student can reside in.
 */
enum Region { CAMPUS, HONG_KONG_ISLAND, KOWLOON, NEW_TERRITORIES, LANTAU_ISLAND, OTHERS };

/**
 * Schools of the university.
 */
enum School { AIS, SBM, SENG, SHSS, SSCI };

/**
 * Modes to match partners with.
 */
enum MatchMode { MOST_SIMILAR, LEAST_SIMILAR };

/**
 * Scores/Factors when calculating scores for partner matching.
 */
const int SAME_YEAR = 5;
const int SAME_SCHOOL = 7;
const int SAME_STUDENT_TYPE = 3;
const int SAME_REGION = 4;
const int SAME_COURSE = 6;
const double SAME_OFFERING_FACTOR = 1.5;

#endif
